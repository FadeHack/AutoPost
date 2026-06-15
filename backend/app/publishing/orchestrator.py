"""Platform-agnostic publish orchestrator.

Replaces the pre-Phase-11 `publish_post(post_id)` with `publish_target(target_id)`.
One job per target — different platforms have different rate limits and failure
modes, so they must be independent.

Responsibilities (none platform-specific):
1. Load PostTarget, Post, and the matching account.
2. Build raw commentary + select assets (carousel-aware, same logic as before).
3. Gate on char_limit — fail fast with PermanentPublishError if exceeded.
4. Status: pending → publishing → published|failed, with PublishingLog rows.
5. Retry classification: auth → forced refresh + once; transient → backoff;
   permanent → stop.
6. Aggregate up to Post: when every target on a Post settles, set
   posts.status = published (any succeeded) or failed (all failed).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.intelligence import generator
from app.models import (
    GeneratedAsset,
    Post,
    PostTarget,
    PublishingLog,
    Template,
)
from app.models.base import (
    Platform,
    PostStatus,
    PublishingStatus,
    TargetStatus,
)
from app.publishing import bluesky as _bluesky  # noqa: F401 — triggers register
from app.publishing import linkedin as _linkedin  # noqa: F401 — triggers register
from app.publishing import mastodon as _mastodon  # noqa: F401 — triggers register
from app.publishing.base import (
    AuthPublishError,
    PermanentPublishError,
    PublishError,
    PublishResult,
    TransientPublishError,
    get_publisher_class,
)

log = structlog.get_logger()

MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0
CAROUSEL_BATCH_WINDOW_SECONDS = 60


# --- Asset selection (carousel-aware) ---


async def _select_publish_assets(
    session: AsyncSession, post: Post
) -> list[GeneratedAsset]:
    """Pick which rendered assets to attach. Identical heuristic to pre-Phase-11
    so the LinkedIn behavior is preserved exactly; other platforms slice
    via `Publisher.max_images`."""
    stmt = (
        select(GeneratedAsset)
        .where(GeneratedAsset.post_id == post.id)
        .order_by(GeneratedAsset.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return []

    template_map = {
        t.id: t
        for t in (await session.execute(select(Template))).scalars().all()
    }

    def is_carousel_slide(a: GeneratedAsset) -> bool:
        tpl = template_map.get(a.template_id)
        return tpl is not None and tpl.name == "carousel_slide"

    if not is_carousel_slide(rows[0]):
        return [rows[0]]

    batch: list[GeneratedAsset] = [rows[0]]
    for a in rows[1:]:
        if not is_carousel_slide(a):
            break
        gap = (batch[-1].created_at - a.created_at).total_seconds()
        if gap > CAROUSEL_BATCH_WINDOW_SECONDS:
            break
        batch.append(a)

    if len(batch) < 2:
        return [rows[0]]
    batch.sort(key=lambda a: a.slide_index if a.slide_index is not None else 0)
    return batch


# --- Commentary (platform-agnostic) ---


def build_commentary(post: Post, target: PostTarget | None = None) -> str:
    """Hook + body + hashtags, no platform-specific escaping. Each Publisher
    impl handles its own escape/format on top.

    If `target.commentary` is set (generator wrote a per-platform rewrite at
    draft-time — currently Bluesky's 300-char compression), it's returned
    verbatim. The fallback is the LinkedIn-canonical assemble from
    `post.hook/body/tags`.
    """
    if target is not None and target.commentary:
        return target.commentary
    cleaned_body = generator.clean_body(post.hook, post.body)
    prose_parts = [post.hook.strip(), cleaned_body.strip()]
    prose = "\n\n".join(p for p in prose_parts if p)
    tag_line = " ".join(f"#{t}" for t in (post.tags or []))
    return f"{prose}\n\n{tag_line}".rstrip() if tag_line else prose


# --- Account loaders ---


async def _load_account(session: AsyncSession, post: Post, platform: Platform):
    if platform == Platform.linkedin:
        return await _linkedin.load_account(session, post)
    if platform == Platform.bluesky:
        return await _bluesky.load_account(session, post)
    if platform == Platform.mastodon:
        return await _mastodon.load_account(session, post)
    raise PermanentPublishError(
        f"no account loader for platform '{platform.value}'"
    )


# --- Post status aggregation ---


async def _maybe_aggregate_post_status(
    session: AsyncSession, post: Post
) -> None:
    """When every PostTarget settles, roll posts.status up to published or
    failed. While any target is still pending/publishing, posts.status stays
    at `scheduled` (or whatever pre-publish state it's in)."""
    stmt = select(PostTarget).where(PostTarget.post_id == post.id)
    targets = list((await session.execute(stmt)).scalars().all())
    if not targets:
        return
    terminal = {TargetStatus.published, TargetStatus.failed}
    if any(t.status not in terminal for t in targets):
        return
    any_published = any(t.status == TargetStatus.published for t in targets)
    new_status = PostStatus.published if any_published else PostStatus.failed
    if post.status != new_status:
        post.status = new_status
        if any_published and post.published_at is None:
            # Earliest target publish wins.
            stamps = [t.published_at for t in targets if t.published_at]
            post.published_at = min(stamps) if stamps else datetime.now(timezone.utc)
        await session.flush()


# --- Main entry ---


async def publish_target(session: AsyncSession, target_id: UUID) -> PostTarget:
    """Publish one PostTarget. Returns the refreshed row.

    Per-target lifecycle: pending → publishing → published|failed.
    Caller (scheduler one-shot or `publish-now` endpoint) is responsible for
    pre-flight timing checks.
    """
    target = await session.get(PostTarget, target_id)
    if target is None:
        raise PermanentPublishError(f"target {target_id} not found")
    if target.status not in (TargetStatus.pending, TargetStatus.publishing):
        raise PermanentPublishError(
            f"cannot publish target in status '{target.status.value}'"
        )

    post = await session.get(Post, target.post_id)
    if post is None:
        raise PermanentPublishError(f"post {target.post_id} not found")

    # Flip target → publishing + commit so concurrent observers see the lock.
    target.status = TargetStatus.publishing
    target.error = None
    await session.commit()
    await session.refresh(target)

    publisher_cls = get_publisher_class(target.platform)
    publisher = publisher_cls()
    account = await _load_account(session, post, target.platform)

    commentary = build_commentary(post, target)
    if len(commentary) > publisher.char_limit:
        target.status = TargetStatus.failed
        target.error = (
            f"commentary {len(commentary)} chars exceeds "
            f"{publisher.platform.value} limit of {publisher.char_limit}"
        )
        session.add(
            PublishingLog(
                post_id=post.id,
                target_id=target.id,
                attempt=1,
                status=PublishingStatus.failure,
                error=target.error,
            )
        )
        await _maybe_aggregate_post_status(session, post)
        await session.commit()
        await session.refresh(target)
        log.warning(
            "publisher.char_limit",
            target_id=str(target.id),
            platform=target.platform.value,
            length=len(commentary),
            limit=publisher.char_limit,
        )
        return target

    assets = await _select_publish_assets(session, post)

    last_err: Exception | None = None
    forced_refresh_used = False

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result: PublishResult = await publisher.publish(
                session=session,
                post=post,
                account=account,
                commentary=commentary,
                assets=assets,
            )
        except PublishError as e:
            kind = (
                "auth"
                if isinstance(e, AuthPublishError)
                else "transient"
                if isinstance(e, TransientPublishError)
                else "permanent"
            )
            session.add(
                PublishingLog(
                    post_id=post.id,
                    target_id=target.id,
                    attempt=attempt,
                    status=PublishingStatus.failure,
                    error=f"{kind}: {str(e)[:900]}",
                )
            )
            last_err = e
            log.warning(
                "publisher.attempt.failed",
                target_id=str(target.id),
                platform=target.platform.value,
                attempt=attempt,
                kind=kind,
            )

            if kind == "auth" and not forced_refresh_used and hasattr(
                account, "refresh_token"
            ) and account.refresh_token:
                # Force a refresh on next attempt even if not technically stale.
                forced_refresh_used = True
                account.expires_at = datetime.now(timezone.utc)
                await session.flush()
                await session.commit()
                continue
            if kind == "permanent":
                break
            if attempt < MAX_ATTEMPTS:
                await session.commit()
                await asyncio.sleep(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
                continue
            await session.commit()
            break
        else:
            session.add(
                PublishingLog(
                    post_id=post.id,
                    target_id=target.id,
                    attempt=attempt,
                    status=PublishingStatus.success,
                    linkedin_response={"urn": result.external_urn},
                )
            )
            target.external_urn = result.external_urn
            target.raw_request = result.raw_request
            target.published_at = datetime.now(timezone.utc)
            target.status = TargetStatus.published
            # Pre-Phase-11 compatibility: stamp posts.linkedin_urn for the
            # first LinkedIn target so any old reads keep working.
            if target.platform == Platform.linkedin and not post.linkedin_urn:
                post.linkedin_urn = result.external_urn
            await _maybe_aggregate_post_status(session, post)
            await session.commit()
            await session.refresh(target)
            log.info(
                "publisher.published",
                target_id=str(target.id),
                platform=target.platform.value,
                urn=result.external_urn,
            )
            return target

    # All attempts exhausted (or permanent fail short-circuited).
    target.status = TargetStatus.failed
    if last_err is not None:
        target.error = str(last_err)[:1000]
    else:
        target.error = "unknown publish error"
    await _maybe_aggregate_post_status(session, post)
    await session.commit()
    await session.refresh(target)
    log.error(
        "publisher.failed",
        target_id=str(target.id),
        platform=target.platform.value,
        error=target.error,
    )
    return target


async def publish_all_targets(
    session: AsyncSession, post_id: UUID
) -> list[PostTarget]:
    """Fan out a publish-now across every target attached to a post.
    Sequential to keep DB session usage simple — fan-out parallelism is
    deferred to the scheduler (one APScheduler job per target). Returns
    refreshed PostTargets in registration order."""
    stmt = (
        select(PostTarget)
        .where(PostTarget.post_id == post_id)
        .order_by(PostTarget.created_at.asc())
    )
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        raise PermanentPublishError(
            f"post {post_id} has no targets — pick platforms at approve time"
        )
    out: list[PostTarget] = []
    for t in rows:
        if t.status not in (TargetStatus.pending, TargetStatus.publishing):
            # Already terminal — skip silently, keep the row in the response so
            # callers can show the full per-platform state.
            await session.refresh(t)
            out.append(t)
            continue
        out.append(await publish_target(session, t.id))
    return out
