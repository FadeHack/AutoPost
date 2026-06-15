"""Publisher orchestration — turns an approved/scheduled Post into a real LinkedIn post.

Layered on top of `linkedin_client.py` (pure HTTP). Responsibilities:

1. Load the Post, its rendered assets, and the connected LinkedInAccount.
2. Ensure the LinkedIn access token is fresh (refresh + re-encrypt on the fly).
3. Download rendered PNG(s) from Supabase Storage.
4. Upload each PNG to LinkedIn → image URN(s).
5. Build the right payload (text-only / single-image / multiImage) and POST.
6. Persist `linkedin_urn`, flip status `publishing → published | failed`, write
   one `PublishingLog` row per attempt.

Retry policy:
- HTTP 401/403 → token issue. Force-refresh and try again, once.
- HTTP 429 / 5xx     → transient. Exponential backoff (2s, 4s), max 3 attempts.
- Other 4xx          → permanent. Mark failed, stop.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import decrypt, encrypt
from app.models import GeneratedAsset, LinkedInAccount, Post, PublishingLog, Template
from app.models.base import AccountKind, PostStatus, PublishingStatus
from app.intelligence import generator
from app.publishing import linkedin_client as lc
from app.publishing import oauth
from app.rendering import pdf as pdf_assembler
from app.rendering import storage

log = structlog.get_logger()

MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0
# Window for grouping carousel slides rendered in a single batch (same as
# the frontend's Phase 4 Chunk G detection).
CAROUSEL_BATCH_WINDOW_SECONDS = 60


class PublishError(Exception):
    """Domain error for the publisher layer. Always paired with a status flip
    on the Post + a PublishingLog row before raising."""


class PermanentPublishError(PublishError):
    pass


class TransientPublishError(PublishError):
    pass


# --- Token freshness ---


async def ensure_fresh_token(
    session: AsyncSession, account: LinkedInAccount
) -> str:
    """Return a usable plaintext access token for the account.

    If the stored token is within `TOKEN_REFRESH_LEAD` of expiry, refresh via
    LinkedIn, re-encrypt + persist, and return the new plaintext. Otherwise
    decrypt + return the existing one. No-op for accounts with no refresh
    token (LinkedIn issued an old grant pre-refresh).
    """
    if not lc._is_token_stale(account.expires_at) or not account.refresh_token:
        return decrypt(account.access_token)

    refresh_plain = decrypt(account.refresh_token)
    log.info("publisher.token.refreshing", account_id=str(account.id))
    new_tokens = await lc.refresh_access_token(refresh_plain)

    account.access_token = encrypt(new_tokens.access_token)
    if new_tokens.refresh_token and new_tokens.refresh_token != refresh_plain:
        account.refresh_token = encrypt(new_tokens.refresh_token)
    account.expires_at = new_tokens.expires_at
    await session.flush()
    log.info(
        "publisher.token.refreshed",
        account_id=str(account.id),
        expires_at=account.expires_at.isoformat(),
    )
    return new_tokens.access_token


# --- Asset selection ---


async def _select_publish_assets(
    session: AsyncSession, post: Post
) -> list[GeneratedAsset]:
    """Pick which rendered assets to attach to the LinkedIn post.

    Detection is asset-shape-driven, not category-driven, so a carousel
    rendered explicitly via the `carousel_slide` template on a non-carousel
    category still publishes as multi-image (matches the frontend
    `currentCarousel` memo on the draft detail page).

    Rules, applied to assets sorted newest-first:
    - If the front-of-list cluster of `carousel_slide` assets within
      `CAROUSEL_BATCH_WINDOW_SECONDS` has >= 2 entries → return that batch
      slide-1-first as a multi-image carousel.
    - Otherwise → return the single most recently rendered asset.
    - No renders at all → `[]` (caller decides text-only vs. fail).
    """
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

    # Front-of-list cluster: stop as soon as either the template changes or
    # the time gap exceeds the window.
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
    # Carousel ordering authoritative: slide_index ASC. created_at is unreliable
    # because Postgres `now()` in a single transaction resolves once, so all
    # slides of one render share the same created_at and the row order is
    # implementation-defined.
    batch.sort(key=lambda a: a.slide_index if a.slide_index is not None else 0)
    return batch


async def _download_png(public_url: str) -> bytes:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        r = await client.get(public_url)
    if r.status_code != 200:
        raise PermanentPublishError(
            f"asset download failed: {r.status_code} {public_url}"
        )
    return r.content


# --- Payload assembly ---


def _build_commentary(post: Post) -> str:
    """Compose LinkedIn commentary from `hook`, `body`, and hashtagged tags.

    The generator already splits hook + body for the editor UX; LinkedIn shows
    them as one continuous string. Hook + blank line + body + blank line +
    hashtags. Escape little-text reserved chars in the prose; tags are appended
    as plain `#tag`s which LinkedIn auto-templates on read.

    Defensive against legacy drafts where `body` still contains a duplicate of
    `hook` as the first line and/or a trailing `#tag #tag` line. Idempotent on
    clean drafts.
    """
    cleaned_body = generator.clean_body(post.hook, post.body)
    prose_parts = [post.hook.strip(), cleaned_body.strip()]
    prose = "\n\n".join(p for p in prose_parts if p)
    escaped = lc.escape_commentary(prose)
    tag_line = " ".join(f"#{t}" for t in (post.tags or []))
    return f"{escaped}\n\n{tag_line}".rstrip() if tag_line else escaped


def _account_author_urn(account: LinkedInAccount) -> str:
    kind = account.account_kind.value if hasattr(account.account_kind, "value") else str(account.account_kind)
    return lc.author_urn(kind, member_sub=account.member_sub, org_urn=account.org_urn)


# --- Single attempt ---


async def _attempt_publish(
    *,
    access_token: str,
    author: str,
    commentary: str,
    assets: list[GeneratedAsset],
) -> tuple[str, dict]:
    """One end-to-end publish attempt. Returns (linkedin_post_urn, raw_request_payload).

    Image upload + post create. Raises `lc.LinkedInAPIError` for HTTP errors —
    the caller classifies + retries.
    """
    if not assets:
        payload = lc.build_text_post_payload(author=author, commentary=commentary)
    elif len(assets) == 1:
        a = assets[0]
        png = await _download_png(storage.public_url(a.image_path))
        image_urn = await lc.upload_image(
            access_token, owner_urn=author, png_bytes=png
        )
        a.linkedin_asset_urn = image_urn
        payload = lc.build_image_post_payload(
            author=author, commentary=commentary, image_urn=image_urn
        )
    else:
        # Multi-slide → native LinkedIn document carousel (swipeable). Render
        # PNGs → assemble PDF → upload as document → create document post.
        # Stamp every slide's GeneratedAsset row with the same document URN so
        # the dashboard can trace back which document any slide belongs to.
        pngs = [
            await _download_png(storage.public_url(a.image_path)) for a in assets
        ]
        pdf_bytes = await pdf_assembler.build_pdf(pngs)
        document_urn = await lc.upload_document(
            access_token, owner_urn=author, pdf_bytes=pdf_bytes
        )
        for a in assets:
            a.linkedin_asset_urn = document_urn
        payload = lc.build_document_post_payload(
            author=author,
            commentary=commentary,
            document_urn=document_urn,
            title="carousel.pdf",
        )

    post_urn = await lc.create_post(access_token, payload)
    return post_urn, payload


# --- Error classification ---


def _classify(err: lc.LinkedInAPIError) -> str:
    """Return one of {'auth', 'transient', 'permanent'}."""
    if err.status in (401, 403):
        return "auth"
    if err.status == 429 or 500 <= err.status < 600:
        return "transient"
    return "permanent"


# --- Main orchestrator ---


async def _load_personal_account(session: AsyncSession) -> LinkedInAccount:
    """MVP: single-user, single connected personal account. Future multi-tenant
    will look this up via a user_id column on Post."""
    stmt = (
        select(LinkedInAccount)
        .where(LinkedInAccount.account_kind == AccountKind.personal)
        .order_by(LinkedInAccount.created_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        raise PermanentPublishError("no connected LinkedIn personal account")
    return row


async def publish_post(session: AsyncSession, post_id: UUID) -> Post:
    """Publish a Post to LinkedIn. Returns the refreshed Post.

    Lifecycle (no skipping): {approved | scheduled} → publishing → {published | failed}.
    Caller is responsible for any pre-flight (e.g. scheduler firing on time).
    """
    post = await session.get(Post, post_id)
    if post is None:
        raise PermanentPublishError(f"post {post_id} not found")
    if post.status not in (PostStatus.approved, PostStatus.scheduled):
        raise PermanentPublishError(
            f"cannot publish post in status '{post.status.value}'"
        )

    # Flip to `publishing` + commit so any concurrent observer sees the lock.
    post.status = PostStatus.publishing
    post.error = None
    await session.commit()
    await session.refresh(post)

    account = await _load_personal_account(session)
    author = _account_author_urn(account)
    assets = await _select_publish_assets(session, post)
    commentary = _build_commentary(post)

    last_err: Exception | None = None
    forced_refresh_used = False

    for attempt in range(1, MAX_ATTEMPTS + 1):
        access_token = await ensure_fresh_token(session, account)
        try:
            urn, payload = await _attempt_publish(
                access_token=access_token,
                author=author,
                commentary=commentary,
                assets=assets,
            )
        except lc.LinkedInAPIError as e:
            kind = _classify(e)
            session.add(
                PublishingLog(
                    post_id=post.id,
                    attempt=attempt,
                    status=PublishingStatus.failure,
                    linkedin_response={"body": e.body[:4000]},
                    error=f"{e.status}: {str(e)[:500]}",
                )
            )
            log.warning(
                "publisher.attempt.failed",
                post_id=str(post.id),
                attempt=attempt,
                status=e.status,
                kind=kind,
            )
            last_err = e

            if kind == "auth" and not forced_refresh_used and account.refresh_token:
                # Force a refresh even if not technically stale — LinkedIn
                # sometimes rejects a token before the documented expiry.
                forced_refresh_used = True
                account.expires_at = datetime.now(tz=timezone.utc)
                await session.flush()
                await session.commit()
                continue
            if kind == "permanent":
                break
            # transient → back off
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
                    attempt=attempt,
                    status=PublishingStatus.success,
                    linkedin_response={"urn": urn},
                )
            )
            post.linkedin_urn = urn
            post.published_at = datetime.now(tz=timezone.utc)
            post.status = PostStatus.published
            post.raw_request = payload
            await session.commit()
            await session.refresh(post)
            log.info("publisher.published", post_id=str(post.id), urn=urn)
            return post

    # All attempts exhausted (or permanent fail short-circuited the loop).
    post.status = PostStatus.failed
    if isinstance(last_err, lc.LinkedInAPIError):
        post.error = f"{last_err.status}: {str(last_err)[:900]}"
    elif last_err is not None:
        post.error = str(last_err)[:1000]
    else:
        post.error = "unknown publish error"
    await session.commit()
    await session.refresh(post)
    log.error(
        "publisher.failed", post_id=str(post.id), error=post.error
    )
    return post
