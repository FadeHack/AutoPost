"""Posts API.

- POST  /posts/generate              — kick off a fresh 4-stage draft for a category
- GET   /posts                       — list, default newest-first
- GET   /posts/{id}                  — fetch one
- PATCH /posts/{id}                  — edit hook/body/tags (only while status='draft')
- POST  /posts/{id}/approve          — draft → approved (lifecycle gate)
- POST  /posts/{id}/schedule         — approved|scheduled → scheduled (idempotent re-time)
- POST  /posts/{id}/render           — render a single visual; persists one GeneratedAsset
- POST  /posts/{id}/render-carousel  — render every slide of a carousel post (one click → N assets)
- GET   /posts/{id}/assets           — list rendered assets for a post
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db import get_session
from app.intelligence.generator import extract_visual_fields, generate_draft
from app.models import GeneratedAsset, Post, PublishingLog, User
from app.models.base import PublishingStatus as PLStatus
from app.models.base import PostCategory, PostStatus, RenderKind
from app.publishing.publisher import publish_post
from app.rendering import storage
from app.rendering.renderer import render_post, render_post_carousel
from app.scheduler.jobs import cancel_publish, schedule_publish
from app.scheduler.scheduler import get_scheduler

router = APIRouter(prefix="/posts", tags=["posts"])


class GenerateRequest(BaseModel):
    category: PostCategory
    trend_ids: list[UUID] | None = None


class PostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category: PostCategory
    status: PostStatus
    hook: str
    body: str
    tags: list[str]
    source_trend_ids: list[UUID]
    # Stage 4 per-template content. NULL for older drafts; backend will lazy-fill
    # on first /render. Shape: {pull_quote, metric_value, metric_label, carousel_slides[{text}]}.
    extracts: dict[str, Any] | None = None
    scheduled_at: datetime | None
    published_at: datetime | None
    linkedin_urn: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime


@router.post("/generate", response_model=PostRead)
async def generate(
    body: GenerateRequest,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PostRead:
    try:
        post = await generate_draft(
            session,
            category=body.category,
            trend_ids=body.trend_ids,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    return PostRead.model_validate(post)


@router.get("", response_model=list[PostRead])
async def list_posts(
    post_status: PostStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list[PostRead]:
    stmt = select(Post).order_by(Post.created_at.desc()).limit(limit)
    if post_status is not None:
        stmt = stmt.where(Post.status == post_status)
    rows = (await session.execute(stmt)).scalars().all()
    return [PostRead.model_validate(r) for r in rows]


@router.get("/{post_id}", response_model=PostRead)
async def get_post(
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PostRead:
    post = await session.get(Post, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="post not found"
        )
    return PostRead.model_validate(post)


# Voice guideline (CLAUDE.md): hashtags lowercase, max 3. We normalize on the
# server so a user pasting "#Python" or "Python" both end up as "python", and
# cap the list at MAX_TAGS to keep manual edits from drifting into hashtag spam.
MAX_TAGS = 6
MAX_TAG_LENGTH = 40


def normalize_tags(raw: list[str]) -> list[str]:
    """Lowercase, strip leading '#' / whitespace, drop empties + duplicates, cap at MAX_TAGS."""
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        cleaned = item.strip().lstrip("#").strip().lower()
        if not cleaned:
            continue
        if len(cleaned) > MAX_TAG_LENGTH:
            cleaned = cleaned[:MAX_TAG_LENGTH]
        if cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
        if len(out) >= MAX_TAGS:
            break
    return out


class PostUpdate(BaseModel):
    """Partial update for a draft. Any omitted field is left unchanged."""

    hook: str | None = Field(default=None, min_length=1, max_length=512)
    body: str | None = Field(default=None, min_length=1)
    tags: list[str] | None = None


@router.patch("/{post_id}", response_model=PostRead)
async def update_post(
    post_id: UUID,
    body: PostUpdate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PostRead:
    """Edit a draft's hook / body / tags. Locked once status leaves `draft`
    so the approval gate is meaningful — to change an approved post, revert
    to draft (not yet exposed) or regenerate."""
    post = await session.get(Post, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="post not found"
        )
    if post.status != PostStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"post is not editable in status '{post.status.value}'",
        )

    body_changed = body.body is not None and body.body.strip() != post.body
    if body.hook is not None:
        post.hook = body.hook.strip()
    if body.body is not None:
        post.body = body.body.strip()
    if body.tags is not None:
        post.tags = normalize_tags(body.tags)

    # Re-run Stage 4 when the body changed so carousel slides + pull-quote
    # reflect the latest text. Hook/tag-only edits skip — Stage 4 is body-driven.
    if body_changed:
        commentary = f"{post.hook}\n\n{post.body}"
        post.extracts = await extract_visual_fields(voiced_text=commentary)

    await session.commit()
    await session.refresh(post)
    return PostRead.model_validate(post)


@router.post("/{post_id}/approve", response_model=PostRead)
async def approve_post(
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PostRead:
    """Mark a draft as approved. Only valid from `draft` per the no-skip
    lifecycle (`draft → approved → scheduled → publishing → published|failed`).
    Approved posts can no longer be edited; to change content, regenerate."""
    post = await session.get(Post, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="post not found"
        )
    if post.status != PostStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot approve post in status '{post.status.value}'",
        )
    post.status = PostStatus.approved
    await session.commit()
    await session.refresh(post)
    return PostRead.model_validate(post)


# Buffer so a post can't be scheduled for "right now" (race against the
# APScheduler tick that lands in Phase 6).
MIN_SCHEDULE_LEAD_SECONDS = 60


class ScheduleRequest(BaseModel):
    scheduled_at: datetime


@router.post("/{post_id}/schedule", response_model=PostRead)
async def schedule_post(
    post_id: UUID,
    body: ScheduleRequest,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PostRead:
    """Schedule (or reschedule) an approved post. Accepts `status` in
    {approved, scheduled} so the caller can adjust the time without
    a separate unschedule step. The APScheduler job that fires at
    `scheduled_at` is wired in Phase 6 — this endpoint just persists
    the intent."""
    post = await session.get(Post, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="post not found"
        )
    if post.status not in (PostStatus.approved, PostStatus.scheduled):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"cannot schedule post in status '{post.status.value}'. "
                "Approve it first."
            ),
        )
    # Normalize to UTC. datetime-local from the browser is naive; assume the
    # client sent an explicit offset or convert naive to UTC at the boundary.
    sched = body.scheduled_at
    if sched.tzinfo is None:
        sched = sched.replace(tzinfo=timezone.utc)
    earliest = datetime.now(timezone.utc) + timedelta(seconds=MIN_SCHEDULE_LEAD_SECONDS)
    if sched < earliest:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"scheduled_at must be at least {MIN_SCHEDULE_LEAD_SECONDS}s in the future"
            ),
        )

    post.scheduled_at = sched
    post.status = PostStatus.scheduled
    await session.commit()
    await session.refresh(post)

    # Register (or replace) the one-shot APScheduler job that fires at `sched`.
    # Idempotent on reschedule via `replace_existing=True` in schedule_publish.
    schedule_publish(get_scheduler(), post.id, sched)

    return PostRead.model_validate(post)


@router.post("/{post_id}/publish-now", response_model=PostRead)
async def publish_now(
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PostRead:
    """Bypass the scheduler and publish inline. Valid from `approved` or
    `scheduled`. If a one-shot APScheduler job exists for this post, cancel
    it first so it doesn't double-fire."""
    post = await session.get(Post, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="post not found"
        )
    if post.status not in (PostStatus.approved, PostStatus.scheduled):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot publish post in status '{post.status.value}'",
        )

    # Drop any pending scheduler job so it doesn't fire after we've already
    # published inline.
    cancel_publish(get_scheduler(), post.id)

    refreshed = await publish_post(session, post_id)
    if refreshed.status == PostStatus.failed:
        # The publisher already wrote a PublishingLog row and set post.error;
        # surface as 502 so the dashboard can render the error inline.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=refreshed.error or "publish failed",
        )
    return PostRead.model_validate(refreshed)


@router.post("/{post_id}/retry", response_model=PostRead)
async def retry_publish(
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PostRead:
    """Reset a `failed` post to `approved` and publish inline. The publisher
    gates on {approved, scheduled}, so retry can't be a thin alias for
    publish-now — we flip status first. Prior PublishingLog rows are kept;
    a new attempt row is appended by the publisher."""
    post = await session.get(Post, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="post not found"
        )
    if post.status != PostStatus.failed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot retry post in status '{post.status.value}'",
        )

    post.status = PostStatus.approved
    post.error = None
    await session.commit()

    refreshed = await publish_post(session, post_id)
    if refreshed.status == PostStatus.failed:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=refreshed.error or "publish failed",
        )
    return PostRead.model_validate(refreshed)


@router.post("/{post_id}/unapprove", response_model=PostRead)
async def unapprove_post(
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PostRead:
    """approved → draft. Reopens the post for editing. No external side effects."""
    post = await session.get(Post, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="post not found"
        )
    if post.status != PostStatus.approved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"can only unapprove from 'approved', not '{post.status.value}'",
        )
    post.status = PostStatus.draft
    await session.commit()
    await session.refresh(post)
    return PostRead.model_validate(post)


@router.post("/{post_id}/unschedule", response_model=PostRead)
async def unschedule_post(
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PostRead:
    """scheduled → approved. Cancels the pending APScheduler one-shot so it
    doesn't fire after the operator pulled the plug."""
    post = await session.get(Post, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="post not found"
        )
    if post.status != PostStatus.scheduled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"can only unschedule from 'scheduled', not '{post.status.value}'",
        )
    cancel_publish(get_scheduler(), post.id)
    post.status = PostStatus.approved
    post.scheduled_at = None
    await session.commit()
    await session.refresh(post)
    return PostRead.model_validate(post)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_post(
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> Response:
    """Hard-delete a draft or failed post. Cascades to generated_assets +
    publishing_logs via DB ON DELETE CASCADE; ai_generations is SET NULL
    so the audit trail survives. Approved/scheduled/publishing/published
    must be lifecycle-reversed first."""
    post = await session.get(Post, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="post not found"
        )
    if post.status not in (PostStatus.draft, PostStatus.failed):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"cannot delete post in status '{post.status.value}'. "
                "Reverse the lifecycle first (unschedule / unapprove)."
            ),
        )
    await session.delete(post)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class PublishingLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    post_id: UUID
    attempt: int
    status: PLStatus
    error: str | None
    linkedin_response: dict[str, Any] | None
    attempted_at: datetime


@router.get("/{post_id}/logs", response_model=list[PublishingLogRead])
async def list_logs(
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list[PublishingLogRead]:
    """All publish attempts for a post, newest-first."""
    stmt = (
        select(PublishingLog)
        .where(PublishingLog.post_id == post_id)
        .order_by(PublishingLog.attempted_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [PublishingLogRead.model_validate(r) for r in rows]


class RenderRequest(BaseModel):
    template_id: UUID | None = None
    # 1-based. Only applies to carousel_slide; ignored by other templates.
    # Out-of-range values are clamped by the renderer, never raise.
    slide_index: int = Field(default=1, ge=1, le=20)
    # 'template' (default) → Playwright + HTML template. 'ai_image' → Flux
    # generation composited into the ai_image_wrap brand template.
    kind: RenderKind = RenderKind.template


class GeneratedAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    post_id: UUID
    template_id: UUID
    image_path: str
    width: int
    height: int
    linkedin_asset_urn: str | None
    render_kind: RenderKind
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def image_url(self) -> str:
        """Public CDN URL from the Supabase Storage bucket."""
        return storage.public_url(self.image_path)


@router.post("/{post_id}/render", response_model=GeneratedAssetRead)
async def render(
    post_id: UUID,
    body: RenderRequest,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> GeneratedAssetRead:
    """Render ONE image — a single template, or one slide of a carousel."""
    try:
        asset = await render_post(
            session,
            post_id=post_id,
            template_id=body.template_id,
            slide_index=body.slide_index,
            kind=body.kind,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    return GeneratedAssetRead.model_validate(asset)


class RenderCarouselRequest(BaseModel):
    """Carousel renders pick ALL slides; the template defaults to the auto-pick
    for the post's category (which is `carousel_slide` for the `carousel`
    category). Caller can override with an explicit `template_id`."""
    template_id: UUID | None = None


@router.post(
    "/{post_id}/render-carousel", response_model=list[GeneratedAssetRead]
)
async def render_carousel(
    post_id: UUID,
    body: RenderCarouselRequest,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list[GeneratedAssetRead]:
    """Render every slide of a carousel post in one call. Returns N assets."""
    try:
        assets = await render_post_carousel(
            session,
            post_id=post_id,
            template_id=body.template_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    return [GeneratedAssetRead.model_validate(a) for a in assets]


@router.get("/{post_id}/assets", response_model=list[GeneratedAssetRead])
async def list_assets(
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list[GeneratedAssetRead]:
    stmt = (
        select(GeneratedAsset)
        .where(GeneratedAsset.post_id == post_id)
        .order_by(GeneratedAsset.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [GeneratedAssetRead.model_validate(r) for r in rows]
