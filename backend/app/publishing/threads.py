"""ThreadsPublisher — raw httpx against Meta's Threads Graph API.

Publishing is always a two-step container flow (web-verified against
developers.facebook.com/docs/threads, 2026-06-16):

  1. Create a media container — POST {graph}/{ver}/{user-id}/threads
       text-only : media_type=TEXT, text=...
       image     : media_type=IMAGE, image_url=<public URL>, text=...
       carousel  : N× media_type=IMAGE&is_carousel_item=true → item ids, then
                   media_type=CAROUSEL, children=<id,id,...>, text=...
  2. Publish it — POST {graph}/{ver}/{user-id}/threads_publish, creation_id=<id>

Media is processed asynchronously, so we poll the container's `status` field
until FINISHED before publishing (and poll each carousel child before assembling
the parent). Char limit 500, carousel 2–20 items.

Tokens are long-lived (60d) and refresh in place — `_ensure_fresh_token`
refreshes proactively on staleness; there is no separate refresh_token, so a
hard 401 degrades to a terminal failure and the operator reconnects.

Meta-gated: only works once Meta App Review approves threads_basic +
threads_content_publish (and pre-approval, only against developer/tester
accounts). No SDK — raw httpx, consistent with `linkedin_client`/`mastodon`.
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
from app.models import GeneratedAsset, Post, ThreadsAccount
from app.models.base import Platform
from app.publishing import threads_oauth as to
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

THREADS_CHAR_LIMIT = 500
THREADS_MAX_IMAGES = 20  # carousel supports 2–20 items
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
    session: AsyncSession, account: ThreadsAccount
) -> str:
    """Return a usable plaintext access token. Refreshes the long-lived token in
    place + re-encrypts if it's within the refresh lead of expiry."""
    plain = decrypt(account.access_token)
    if not _is_token_stale(account.expires_at):
        return plain
    log.info("threads.token.refreshing", account_id=str(account.id))
    refreshed = await to.refresh_long_lived(plain)
    account.access_token = encrypt(refreshed.access_token)
    account.expires_at = refreshed.expires_at
    await session.flush()
    log.info(
        "threads.token.refreshed",
        account_id=str(account.id),
        expires_at=refreshed.expires_at.isoformat(),
    )
    return refreshed.access_token


def _classify(status_code: int, body: str) -> Exception:
    """Map a Threads/Meta Graph error onto the abstract PublishError taxonomy.

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


def _base(account: ThreadsAccount) -> str:
    return f"{to.GRAPH_BASE}/{settings.THREADS_API_VERSION}/{account.threads_user_id}"


async def _create_container(
    client: httpx.AsyncClient, base: str, token: str, params: dict[str, Any]
) -> str:
    r = await client.post(
        f"{base}/threads", data={**params, "access_token": token}
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
    """Poll a container's status until FINISHED. Raises on ERROR/EXPIRED or if
    it never finishes within the poll budget."""
    status_url = f"{to.GRAPH_BASE}/{settings.THREADS_API_VERSION}/{container_id}"
    for _ in range(CONTAINER_POLL_ATTEMPTS):
        r = await client.get(
            status_url,
            params={"fields": "status,error_message", "access_token": token},
        )
        if r.status_code != 200:
            raise _classify(r.status_code, r.text)
        body = r.json()
        status = body.get("status")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise PermanentPublishError(
                f"container {container_id} {status}: {body.get('error_message')}"
            )
        await asyncio.sleep(CONTAINER_POLL_INTERVAL_SECONDS)
    raise TransientPublishError(
        f"container {container_id} not FINISHED after {CONTAINER_POLL_ATTEMPTS} polls"
    )


async def _publish_container(
    client: httpx.AsyncClient, base: str, token: str, creation_id: str
) -> str:
    r = await client.post(
        f"{base}/threads_publish",
        data={"creation_id": creation_id, "access_token": token},
    )
    if r.status_code != 200:
        raise _classify(r.status_code, r.text)
    mid = r.json().get("id")
    if not mid:
        raise PermanentPublishError("threads_publish returned no id")
    return mid


@register
class ThreadsPublisher(Publisher):
    platform = Platform.threads
    char_limit = THREADS_CHAR_LIMIT
    max_images = THREADS_MAX_IMAGES
    supports_documents = False

    async def publish(
        self,
        *,
        session: AsyncSession,
        post: Post,  # noqa: ARG002 — parity; text comes from commentary
        account: ThreadsAccount,
        commentary: str,
        assets: list[GeneratedAsset],
    ) -> PublishResult:
        token = await _ensure_fresh_token(session, account)
        base = _base(account)
        attach = assets[:THREADS_MAX_IMAGES]
        # Threads fetches image bytes from a public URL itself.
        image_urls = [storage.public_url(a.image_path) for a in attach]

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            if not image_urls:
                container_id = await _create_container(
                    client, base, token,
                    {"media_type": "TEXT", "text": commentary},
                )
            elif len(image_urls) == 1:
                container_id = await _create_container(
                    client, base, token,
                    {
                        "media_type": "IMAGE",
                        "image_url": image_urls[0],
                        "text": commentary,
                    },
                )
            else:
                item_ids: list[str] = []
                for url in image_urls:
                    item_id = await _create_container(
                        client, base, token,
                        {
                            "media_type": "IMAGE",
                            "image_url": url,
                            "is_carousel_item": "true",
                        },
                    )
                    await _poll_until_finished(client, item_id, token)
                    item_ids.append(item_id)
                container_id = await _create_container(
                    client, base, token,
                    {
                        "media_type": "CAROUSEL",
                        "children": ",".join(item_ids),
                        "text": commentary,
                    },
                )

            await _poll_until_finished(client, container_id, token)
            media_id = await _publish_container(client, base, token, container_id)

        return PublishResult(
            external_urn=media_id,
            raw_request={"text": commentary, "image_count": len(image_urls)},
        )


# --- Account loader (used by orchestrator) ---


async def load_account(
    session: AsyncSession, post: Post
) -> ThreadsAccount:
    from sqlalchemy import select

    row = (
        await session.execute(
            select(ThreadsAccount)
            .where(ThreadsAccount.workspace_id == post.workspace_id)
            .order_by(ThreadsAccount.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if row is None:
        raise PermanentPublishError("no connected Threads account")
    return row
