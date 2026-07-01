"""Posts API.

- POST  /posts/generate              — kick off a fresh 5-stage draft for a category
- GET   /posts                       — list, default newest-first
- GET   /posts/{id}                  — fetch one
- PATCH /posts/{id}                  — edit hook/body/tags (only while status='draft')
- POST  /posts/{id}/approve          — draft → approved + create PostTarget rows
- POST  /posts/{id}/schedule         — approved|scheduled → scheduled (fans out per target)
- POST  /posts/{id}/publish-now      — publish inline to every PostTarget
- POST  /posts/{id}/render           — render a single visual; persists one GeneratedAsset
- POST  /posts/{id}/render-carousel  — render every slide of a carousel post
- GET   /posts/{id}/assets           — list rendered assets for a post
- GET   /posts/{id}/targets          — list per-platform PostTarget rows
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db import get_session
from app.intelligence.generator import extract_visual_fields, generate_draft
from app.models import GeneratedAsset, Post, PostTarget, PublishingLog, User
from app.models.base import PublishingStatus as PLStatus
from app.models.base import Platform, PostCategory, PostStatus, RenderKind, TargetStatus
from app.publishing.orchestrator import publish_all_targets
from app.rendering import storage
from app.rendering.renderer import render_post, render_post_carousel
from app.scheduler.jobs import (
    cancel_target_publish,
    schedule_target_publish,
)
from app.scheduler.scheduler import get_scheduler

router = APIRouter(prefix="/posts", tags=["posts"])


class GenerateRequest(BaseModel):
    category: PostCategory
    trend_ids: list[UUID] | None = None
    # Phase 11 Chunk A follow-up: platforms move pre-generation so the
    # generator can rewrite per-platform (Bluesky 300-char compress, etc.)
    # instead of failing the char-limit gate at publish. Default keeps the
    # old behavior for clients that haven't migrated.
    platforms: list[Platform] = Field(default_factory=lambda: [Platform.linkedin])


class PostTargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    post_id: UUID
    platform: Platform
    status: TargetStatus
    scheduled_at: datetime | None
    published_at: datetime | None
    external_urn: str | None
    error: str | None
    # Platform-specific commentary (Bluesky's compressed variant, etc.).
    # NULL = orchestrator falls back to Post.hook/body/tags.
    commentary: str | None
    created_at: datetime
    updated_at: datetime


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
    # Legacy single-platform field; Phase 11+ sources from PostTarget.external_urn.
    linkedin_urn: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    # Per-platform fan-out. Empty for new drafts; populated at approve time.
    targets: list[PostTargetRead] = Field(default_factory=list)


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
            platforms=body.platforms,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    return PostRead.model_validate(post)


@router.get("", response_model=list[PostRead])
async def list_posts(
    status: str | None = Query(
        None,
        description="One status or a comma list (e.g. 'scheduled,publishing'). "
        "Lets the board/calendar fetch only the statuses they render instead of "
        "pulling everything and filtering client-side.",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, description="Skip N rows — drives 'Load more'."),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list[PostRead]:
    stmt = (
        select(Post).order_by(Post.created_at.desc()).limit(limit).offset(offset)
    )
    if status:
        try:
            wanted = [PostStatus(s) for s in status.split(",") if s]
        except ValueError as exc:
            # `status` (the query param) shadows the fastapi status module here,
            # so use the literal 400.
            raise HTTPException(
                status_code=400, detail=f"invalid status filter: {exc}"
            ) from exc
        stmt = stmt.where(Post.status.in_(wanted))
    rows = (await session.execute(stmt)).scalars().all()
    return [PostRead.model_validate(r) for r in rows]


class PostStats(BaseModel):
    """Counts by status for the funnel/badges — so Today and the NavRail can
    render numbers without shipping hundreds of full PostRead rows just to
    `.length` them client-side. `published_7d` powers Today's recent-activity
    counter (status counts are all-time)."""

    draft: int = 0
    approved: int = 0
    scheduled: int = 0
    publishing: int = 0
    published: int = 0
    failed: int = 0
    published_7d: int = 0


@router.get("/stats", response_model=PostStats)
async def post_stats(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PostStats:
    """Aggregate counts (one GROUP BY + one filtered count) — cheap on the DB,
    replaces the 5–7 full-list fetches the dashboard used to do for counts."""
    rows = (
        await session.execute(
            select(Post.status, func.count()).group_by(Post.status)
        )
    ).all()
    counts = {st.value: n for st, n in rows}

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    published_7d = (
        await session.execute(
            select(func.count())
            .select_from(Post)
            .where(Post.status == PostStatus.published, Post.published_at >= cutoff)
        )
    ).scalar_one()

    return PostStats(**counts, published_7d=published_7d)


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


class ApproveRequest(BaseModel):
    """Targets now picked at generate-time, so approve is a pure status flip.

    `targets` is kept as an OPTIONAL legacy field: if a draft was generated
    with no targets (pre-migration UI, or curl with the old shape) and the
    operator supplies targets here, we still create them on approve so the
    old workflow doesn't 409. New flows leave it empty.
    """
    targets: list[Platform] = Field(default_factory=list)


@router.post("/{post_id}/approve", response_model=PostRead)
async def approve_post(
    post_id: UUID,
    body: ApproveRequest,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PostRead:
    """draft → approved. Targets are normally already attached (pre-generated)
    so this is just a status flip. For legacy back-fill, accepts `targets` and
    creates rows on the fly if the draft has none."""
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
    if not post.targets and not body.targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "draft has no targets attached — regenerate with platforms, "
                "or pass targets on approve"
            ),
        )
    if not post.targets and body.targets:
        # Legacy path: backfill targets at approve.
        seen: set[Platform] = set()
        for p in body.targets:
            if p in seen:
                continue
            seen.add(p)
            session.add(PostTarget(post_id=post.id, platform=p))
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
    """Schedule (or reschedule) an approved post for ALL its targets.

    One APScheduler one-shot per target fires at `scheduled_at` — each
    platform runs its own retry loop and writes its own PublishingLog rows.
    Idempotent on reschedule via `replace_existing=True` per target.
    """
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
    if not post.targets:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="post has no targets — re-approve with at least one platform",
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
    # Update every pending target with the same wall-clock. Already-terminal
    # targets (published/failed) are left alone — operator must retry them
    # explicitly.
    for t in post.targets:
        if t.status in (TargetStatus.pending,):
            t.scheduled_at = sched

    await session.commit()
    await session.refresh(post)

    # Register one APScheduler one-shot per pending target.
    scheduler = get_scheduler()
    for t in post.targets:
        if t.status == TargetStatus.pending:
            schedule_target_publish(scheduler, t.id, sched)

    return PostRead.model_validate(post)


@router.post("/{post_id}/publish-now", response_model=PostRead)
async def publish_now(
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PostRead:
    """Bypass the scheduler and publish inline to every PostTarget.

    Fans out sequentially — one platform's failure does not block the others
    (each target gets its own retry loop). Returns 502 if every target ended
    up failed, 200 otherwise so partial-success is visible to the dashboard.
    """
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
    if not post.targets:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="post has no targets — re-approve with at least one platform",
        )

    # Drop any pending scheduler jobs for these targets so they don't
    # double-fire after we've already published inline.
    scheduler = get_scheduler()
    for t in post.targets:
        cancel_target_publish(scheduler, t.id)

    targets = await publish_all_targets(session, post_id)
    await session.refresh(post)

    failed = [t for t in targets if t.status == TargetStatus.failed]
    if failed and len(failed) == len(targets):
        # Every platform failed → surface 502 so dashboard renders an error.
        msgs = [
            f"{t.platform.value}: {t.error or 'unknown'}"
            for t in targets
            if t.error
        ]
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=" | ".join(msgs) or "publish failed",
        )
    if failed:
        # Partial — surface in post.error so dashboard's existing error panel
        # shows what went wrong on which platform, without 5xx-ing the
        # successful ones.
        post.error = " | ".join(
            f"{t.platform.value}: {t.error or 'unknown'}" for t in failed
        )
        await session.commit()
        await session.refresh(post)
    else:
        # Clean run — wipe any stale error from a prior partial attempt.
        if post.error:
            post.error = None
            await session.commit()
            await session.refresh(post)
    return PostRead.model_validate(post)


@router.post("/{post_id}/retry", response_model=PostRead)
async def retry_publish(
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PostRead:
    """Re-attempt every `failed` target on a post. Each failed target flips
    back to `pending` (clearing its error) and the orchestrator re-fans out.
    Already-published targets are untouched."""
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
    # Move post off the terminal state so the aggregator can re-run.
    post.status = PostStatus.scheduled
    post.error = None
    for t in post.targets:
        if t.status == TargetStatus.failed:
            t.status = TargetStatus.pending
            t.error = None
    await session.commit()

    targets = await publish_all_targets(session, post_id)
    await session.refresh(post)
    failed = [t for t in targets if t.status == TargetStatus.failed]
    if failed and len(failed) == len(targets):
        msgs = [
            f"{t.platform.value}: {t.error or 'unknown'}"
            for t in targets
            if t.error
        ]
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=" | ".join(msgs) or "publish failed",
        )
    if failed:
        post.error = " | ".join(
            f"{t.platform.value}: {t.error or 'unknown'}" for t in failed
        )
        await session.commit()
        await session.refresh(post)
    else:
        if post.error:
            post.error = None
            await session.commit()
            await session.refresh(post)
    return PostRead.model_validate(post)


@router.post("/{post_id}/unapprove", response_model=PostRead)
async def unapprove_post(
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PostRead:
    """approved → draft. Drops every PostTarget (operator re-picks platforms
    on the next approve). Reopens the post for editing."""
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
    # Wipe targets — re-approval is the supported path to change which
    # platforms a draft fans out to.
    for t in list(post.targets):
        await session.delete(t)
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
    """scheduled → approved. Cancels every pending APScheduler one-shot so
    they don't fire after the operator pulled the plug. Targets stay
    attached — operator can reschedule without re-picking platforms."""
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
    scheduler = get_scheduler()
    for t in post.targets:
        cancel_target_publish(scheduler, t.id)
        if t.status == TargetStatus.pending:
            t.scheduled_at = None
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
    # Only applies to kind='ai_image'. How much brand chrome wraps the Flux
    # image: 'card' (default) = full black brand card, 'mark' = full-bleed +
    # small corner brand mark, 'none' = full-bleed no chrome.
    frame: Literal["card", "mark", "none"] = "card"


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
            frame=body.frame,
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


@router.get("/{post_id}/targets", response_model=list[PostTargetRead])
async def list_targets(
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list[PostTargetRead]:
    """Per-platform PostTarget rows for a post, oldest-first (creation order
    matches the operator's pick order at approve time)."""
    stmt = (
        select(PostTarget)
        .where(PostTarget.post_id == post_id)
        .order_by(PostTarget.created_at.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [PostTargetRead.model_validate(r) for r in rows]


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
