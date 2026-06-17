"""InstagramPublisher — raw httpx against Meta's Instagram Graph API.

Publishing is the two-step container flow (web-verified against
developers.facebook.com/docs/instagram-platform/content-publishing, 2026-06-16):

  1. Create a media container — POST {graph}/{ver}/{ig-user-id}/media
       image    : image_url=<public URL>, caption=...
       carousel : N× image_url=...&is_carousel_item=true → item ids, then
                  media_type=CAROUSEL, children=<id,id,...>, caption=...
  2. Publish it — POST {graph}/{ver}/{ig-user-id}/media_publish, creation_id=<id>

Unlike Threads, **Instagram has no text-only post** — every container needs an
image, so an empty asset list is a permanent failure. Media is processed
asynchronously, so we poll the container's `status_code` field until FINISHED
before publishing (and poll each carousel child before assembling the parent).
Caption limit 2200 chars, carousel 2–10 items, square (1080×1080) or 4:5 images.

Tokens are long-lived (60d) and refresh in place — `_ensure_fresh_token`
refreshes proactively on staleness; there is no separate refresh_token, so a
hard 401 degrades to a terminal failure and the operator reconnects.

Meta-gated: only works once Meta App Review approves the Instagram content
publishing scope (and pre-approval, only against developer/tester accounts).
No SDK — raw httpx, consistent with `linkedin`/`mastodon`/`threads`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import decrypt, encrypt
from app.models import GeneratedAsset, InstagramAccount, Post
from app.models.base import Platform
from app.publishing import instagram_oauth as io
from app.publishing.base import (
    AuthPublishError,
    PermanentPublishError,
    PublishResult,
    Publisher,
    TransientPublishError,
    register,
)
from app.rendering import storage

log = structlog.get_logger()

INSTAGRAM_CHAR_LIMIT = 2200
INSTAGRAM_MAX_IMAGES = 10  # carousel supports 2–10 items
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
# Long-lived tokens last ~60 days; refresh once inside the lead window. The
# refresh endpoint requires the token to be ≥24h old, which any near-expiry
# (60-day-old) token trivially satisfies.
TOKEN_REFRESH_LEAD = timedelta(days=2)
# Container media-processing poll budget.
CONTAINER_POLL_ATTEMPTS = 15
CONTAINER_POLL_INTERVAL_SECONDS = 2.0


def _is_token_stale(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(tz=timezone.utc) + TOKEN_REFRESH_LEAD


async def _ensure_fresh_token(
    session: AsyncSession, account: InstagramAccount
) -> str:
    """Return a usable plaintext access token. Refreshes the long-lived token in
    place + re-encrypts if it's within the refresh lead of expiry."""
    plain = decrypt(account.access_token)
    if not _is_token_stale(account.expires_at):
        return plain
    log.info("instagram.token.refreshing", account_id=str(account.id))
    refreshed = await io.refresh_long_lived(plain)
    account.access_token = encrypt(refreshed.access_token)
    account.expires_at = refreshed.expires_at
    await session.flush()
    log.info(
        "instagram.token.refreshed",
        account_id=str(account.id),
        expires_at=refreshed.expires_at.isoformat(),
    )
    return refreshed.access_token


def _classify(status_code: int, body: str) -> Exception:
    """Map an Instagram/Meta Graph error onto the abstract PublishError taxonomy.

    Meta often returns 400 for an expired/invalid token (OAuthException,
    code 190) rather than 401, so we sniff the body for that case."""
    lowered = body.lower()
    if status_code in (401, 403) or "oauthexception" in lowered or '"code":190' in body.replace(
        " ", ""
    ):
        return AuthPublishError(f"{status_code}: {body[:300]}")
    if status_code == 429 or 500 <= status_code < 600:
        return TransientPublishError(f"{status_code}: {body[:300]}")
    return PermanentPublishError(f"{status_code}: {body[:300]}")


def _base(account: InstagramAccount) -> str:
    return (
        f"{io.GRAPH_BASE}/{settings.INSTAGRAM_API_VERSION}"
        f"/{account.instagram_user_id}"
    )


async def _create_container(
    client: httpx.AsyncClient, base: str, token: str, params: dict[str, Any]
) -> str:
    r = await client.post(
        f"{base}/media", data={**params, "access_token": token}
    )
    if r.status_code != 200:
        raise _classify(r.status_code, r.text)
    cid = r.json().get("id")
    if not cid:
        raise PermanentPublishError("container create returned no id")
    return cid


async def _poll_until_finished(
    client: httpx.AsyncClient, container_id: str, token: str
) -> None:
    """Poll a container's status_code until FINISHED. Raises on ERROR/EXPIRED
    or if it never finishes within the poll budget."""
    status_url = f"{io.GRAPH_BASE}/{settings.INSTAGRAM_API_VERSION}/{container_id}"
    for _ in range(CONTAINER_POLL_ATTEMPTS):
        r = await client.get(
            status_url,
            params={"fields": "status_code,status", "access_token": token},
        )
        if r.status_code != 200:
            raise _classify(r.status_code, r.text)
        body = r.json()
        code = body.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise PermanentPublishError(
                f"container {container_id} {code}: {body.get('status')}"
            )
        await asyncio.sleep(CONTAINER_POLL_INTERVAL_SECONDS)
    raise TransientPublishError(
        f"container {container_id} not FINISHED after {CONTAINER_POLL_ATTEMPTS} polls"
    )


async def _publish_container(
    client: httpx.AsyncClient, base: str, token: str, creation_id: str
) -> str:
    r = await client.post(
        f"{base}/media_publish",
        data={"creation_id": creation_id, "access_token": token},
    )
    if r.status_code != 200:
        raise _classify(r.status_code, r.text)
    mid = r.json().get("id")
    if not mid:
        raise PermanentPublishError("media_publish returned no id")
    return mid


@register
class InstagramPublisher(Publisher):
    platform = Platform.instagram
    char_limit = INSTAGRAM_CHAR_LIMIT
    max_images = INSTAGRAM_MAX_IMAGES
    supports_documents = False

    async def publish(
        self,
        *,
        session: AsyncSession,
        post: Post,  # noqa: ARG002 — parity; text comes from commentary
        account: InstagramAccount,
        commentary: str,
        assets: list[GeneratedAsset],
    ) -> PublishResult:
        attach = assets[:INSTAGRAM_MAX_IMAGES]
        if not attach:
            # Instagram requires media — there is no text-only feed post.
            raise PermanentPublishError(
                "Instagram requires at least one image; render a card first"
            )

        token = await _ensure_fresh_token(session, account)
        base = _base(account)
        # Instagram fetches image bytes from a public URL itself.
        image_urls = [storage.public_url(a.image_path) for a in attach]

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            if len(image_urls) == 1:
                container_id = await _create_container(
                    client, base, token,
                    {"image_url": image_urls[0], "caption": commentary},
                )
            else:
                item_ids: list[str] = []
                for url in image_urls:
                    item_id = await _create_container(
                        client, base, token,
                        {"image_url": url, "is_carousel_item": "true"},
                    )
                    await _poll_until_finished(client, item_id, token)
                    item_ids.append(item_id)
                container_id = await _create_container(
                    client, base, token,
                    {
                        "media_type": "CAROUSEL",
                        "children": ",".join(item_ids),
                        "caption": commentary,
                    },
                )

            await _poll_until_finished(client, container_id, token)
            media_id = await _publish_container(client, base, token, container_id)

        return PublishResult(
            external_urn=media_id,
            raw_request={"caption": commentary, "image_count": len(image_urls)},
        )


# --- Account loader (used by orchestrator) ---


async def load_account(
    session: AsyncSession, post: Post  # noqa: ARG001 — parity with other loaders
) -> InstagramAccount:
    from sqlalchemy import select

    row = (
        await session.execute(
            select(InstagramAccount)
            .order_by(InstagramAccount.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if row is None:
        raise PermanentPublishError("no connected Instagram account")
    return row
