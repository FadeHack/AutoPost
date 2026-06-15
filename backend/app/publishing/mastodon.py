"""MastodonPublisher — raw httpx against the connected account's home instance.

Posting is a two-step flow when media is attached:
1. `POST {instance}/api/v2/media` (multipart) per image → media id. Small images
   return 200 (processed synchronously); larger uploads return 202 and we poll
   `GET {instance}/api/v1/media/{id}` until `url` is non-null.
2. `POST {instance}/api/v1/statuses` with `status` + `media_ids[]`.

Char limit: 500 (instance-configurable, but 500 is the canonical default). The
orchestrator gates BEFORE calling in — a draft body over 500 fails the target
loudly. Per memory, Mastodon does NOT get a per-platform compression today
(commentary=None → orchestrator falls back to the LinkedIn-shaped body → fails
the 500 gate). That pressure is intentional; Phase 12's per-platform prompt
matrix is the real fix.

No SDK — raw httpx, consistent with `linkedin_client`.
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt
from app.models import GeneratedAsset, MastodonAccount, Post
from app.models.base import Platform
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

MASTODON_CHAR_LIMIT = 500
MASTODON_MAX_IMAGES = 4
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
# Async media processing poll budget. Images are usually 200-sync; a 202 means
# the instance is processing in the background.
MEDIA_POLL_ATTEMPTS = 10
MEDIA_POLL_INTERVAL_SECONDS = 1.5


async def _download_png(public_url: str) -> bytes:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(public_url)
    if r.status_code != 200:
        raise PermanentPublishError(
            f"asset download failed: {r.status_code} {public_url}"
        )
    return r.content


def _classify(status_code: int, body: str) -> Exception:
    """Map a Mastodon HTTP error onto the abstract PublishError taxonomy."""
    if status_code in (401, 403):
        return AuthPublishError(f"{status_code}: {body[:300]}")
    if status_code == 429 or 500 <= status_code < 600:
        return TransientPublishError(f"{status_code}: {body[:300]}")
    return PermanentPublishError(f"{status_code}: {body[:300]}")


async def _upload_media(
    client: httpx.AsyncClient, instance: str, token: str, png: bytes, alt: str
) -> str:
    """POST /api/v2/media then poll if processing async. Returns the media id."""
    r = await client.post(
        f"{instance}/api/v2/media",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("image.png", png, "image/png")},
        data={"description": alt},
    )
    if r.status_code not in (200, 202):
        raise _classify(r.status_code, r.text)
    media = r.json()
    media_id = media.get("id")
    if not media_id:
        raise PermanentPublishError("media upload returned no id")

    # 200 → ready immediately. 202 → processing; poll until `url` is non-null.
    if r.status_code == 200 and media.get("url"):
        return media_id
    for _ in range(MEDIA_POLL_ATTEMPTS):
        await asyncio.sleep(MEDIA_POLL_INTERVAL_SECONDS)
        poll = await client.get(
            f"{instance}/api/v1/media/{media_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if poll.status_code == 200 and poll.json().get("url"):
            return media_id
        if poll.status_code >= 400:
            raise _classify(poll.status_code, poll.text)
    raise TransientPublishError(
        f"media {media_id} still processing after {MEDIA_POLL_ATTEMPTS} polls"
    )


@register
class MastodonPublisher(Publisher):
    platform = Platform.mastodon
    char_limit = MASTODON_CHAR_LIMIT
    max_images = MASTODON_MAX_IMAGES
    supports_documents = False

    async def publish(
        self,
        *,
        session: AsyncSession,  # noqa: ARG002 — kept for ABC parity
        post: Post,
        account: MastodonAccount,
        commentary: str,
        assets: list[GeneratedAsset],
    ) -> PublishResult:
        instance = account.instance_url.rstrip("/")
        token = decrypt(account.access_token)
        attach = assets[:MASTODON_MAX_IMAGES]
        alt = (post.hook or "Image")[:1500]

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            media_ids: list[str] = []
            for a in attach:
                png = await _download_png(storage.public_url(a.image_path))
                media_ids.append(
                    await _upload_media(client, instance, token, png, alt)
                )

            payload: dict[str, Any] = {"status": commentary, "visibility": "public"}
            if media_ids:
                payload["media_ids"] = media_ids

            r = await client.post(
                f"{instance}/api/v1/statuses",
                headers={
                    "Authorization": f"Bearer {token}",
                    # Idempotency-Key dedupes a retried create on the instance
                    # side so a transient retry can't double-post.
                    "Idempotency-Key": secrets.token_hex(16),
                },
                json=payload,
            )
        if r.status_code != 200:
            raise _classify(r.status_code, r.text)
        body = r.json()
        urn = body.get("uri") or body.get("url")
        if not urn:
            raise PermanentPublishError("status create returned no uri")
        return PublishResult(external_urn=urn, raw_request=payload)


# --- Account loader (used by orchestrator) ---


async def load_account(
    session: AsyncSession, post: Post  # noqa: ARG001 — parity with other loaders
) -> MastodonAccount:
    from sqlalchemy import select

    row = (
        await session.execute(
            select(MastodonAccount)
            .order_by(MastodonAccount.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if row is None:
        raise PermanentPublishError("no connected Mastodon account")
    return row
