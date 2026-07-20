"""XPublisher — raw httpx against the X (Twitter) API v2.

Publishing is a two-step flow (web-verified against docs.x.com, 2026-07):

  1. Upload each image — POST https://api.x.com/2/media/upload
       multipart/form-data: media=<bytes>, media_category=tweet_image,
       media_type=image/png|jpeg  →  response data.id = media_id
     (single-request "one-shot" upload; our renders are well under the 5 MB cap,
      so no chunked INIT/APPEND/FINALIZE dance is needed.)
  2. Create the post — POST https://api.x.com/2/tweets
       JSON {"text": ..., "media": {"media_ids": [...]}}  →  201, data.id = tweet id

Char limit 280 (standard tier). Up to 4 images per post. Unlike the Meta
platforms, X does NOT fetch image bytes from a URL — we upload the bytes
ourselves, so the public Supabase URL is downloaded first.

Auth: OAuth2 user-context bearer token. Access tokens are short-lived (~2h) with
a ROTATING refresh token (offline.access), so `_ensure_fresh_token` refreshes
proactively and re-persists BOTH tokens. `media.write` scope is required for the
upload; `tweet.write` for the post.

PAID API — no free tier for new developers as of 2026 (~$0.015 per post).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt, encrypt
from app.models import GeneratedAsset, Post, XAccount
from app.models.base import Platform
from app.publishing import x_oauth as xo
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

X_CHAR_LIMIT = 280
X_MAX_IMAGES = 4
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
# Access tokens live ~2h; refresh once inside this lead so a publish never runs
# on a token that expires mid-flight.
TOKEN_REFRESH_LEAD = timedelta(minutes=5)

MEDIA_UPLOAD_URL = "https://api.x.com/2/media/upload"
TWEETS_URL = "https://api.x.com/2/tweets"


def _is_token_stale(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(tz=timezone.utc) + TOKEN_REFRESH_LEAD


async def _ensure_fresh_token(session: AsyncSession, account: XAccount) -> str:
    """Return a usable plaintext access token. Refreshes proactively when the
    short-lived token is within the refresh lead, re-encrypting BOTH the new
    access token and the rotated refresh token."""
    plain = decrypt(account.access_token)
    if not _is_token_stale(account.expires_at):
        return plain
    if not account.refresh_token:
        # No refresh token → nothing to do; let the stale token try and 401 if
        # dead (orchestrator surfaces it as an auth failure → reconnect).
        return plain
    log.info("x.token.refreshing", account_id=str(account.id))
    refreshed = await xo.refresh_token(decrypt(account.refresh_token))
    account.access_token = encrypt(refreshed.access_token)
    if refreshed.refresh_token:
        account.refresh_token = encrypt(refreshed.refresh_token)
    account.expires_at = refreshed.expires_at
    await session.flush()
    log.info(
        "x.token.refreshed",
        account_id=str(account.id),
        expires_at=refreshed.expires_at.isoformat(),
    )
    return refreshed.access_token


def _classify(status_code: int, body: str) -> Exception:
    """Map an X API error onto the abstract PublishError taxonomy. 401 → auth
    (forced refresh + retry once); 429/5xx → transient; everything else (incl.
    403 duplicate-content / permission) → permanent."""
    if status_code == 401:
        return AuthPublishError(f"{status_code}: {body[:300]}")
    if status_code == 429 or 500 <= status_code < 600:
        return TransientPublishError(f"{status_code}: {body[:300]}")
    return PermanentPublishError(f"{status_code}: {body[:300]}")


async def _download(public_url: str) -> bytes:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(public_url)
    if r.status_code != 200:
        raise PermanentPublishError(
            f"asset download failed: {r.status_code} {public_url}"
        )
    return r.content


def _content_type_for(path: str) -> str:
    return "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"


async def _upload_media(
    client: httpx.AsyncClient, token: str, data: bytes, content_type: str
) -> str:
    """One-shot media upload → media_id. Bytes are well under 5 MB so no
    chunking is needed."""
    r = await client.post(
        MEDIA_UPLOAD_URL,
        headers={"Authorization": f"Bearer {token}"},
        data={"media_category": "tweet_image", "media_type": content_type},
        files={"media": ("asset", data, content_type)},
    )
    if r.status_code not in (200, 201):
        raise _classify(r.status_code, r.text)
    media_id = (r.json().get("data") or {}).get("id")
    if not media_id:
        raise PermanentPublishError("media upload returned no id")
    return str(media_id)


@register
class XPublisher(Publisher):
    platform = Platform.x
    char_limit = X_CHAR_LIMIT
    max_images = X_MAX_IMAGES
    supports_documents = False

    async def publish(
        self,
        *,
        session: AsyncSession,
        post: Post,  # noqa: ARG002 — parity; text comes from commentary
        account: XAccount,
        commentary: str,
        assets: list[GeneratedAsset],
    ) -> PublishResult:
        token = await _ensure_fresh_token(session, account)
        attach = assets[:X_MAX_IMAGES]

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            media_ids: list[str] = []
            for a in attach:
                png = await _download(storage.public_url(a.image_path))
                media_ids.append(
                    await _upload_media(
                        client, token, png, _content_type_for(a.image_path)
                    )
                )

            payload: dict[str, Any] = {"text": commentary}
            if media_ids:
                payload["media"] = {"media_ids": media_ids}

            r = await client.post(
                TWEETS_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if r.status_code != 201:
            raise _classify(r.status_code, r.text)
        tweet_id = (r.json().get("data") or {}).get("id")
        if not tweet_id:
            raise PermanentPublishError("tweet create returned no id")

        return PublishResult(
            external_urn=str(tweet_id),
            raw_request={"text": commentary, "image_count": len(media_ids)},
        )


# --- Account loader (used by orchestrator) ---


async def load_account(
    session: AsyncSession, post: Post
) -> XAccount:
    from sqlalchemy import select

    row = (
        await session.execute(
            select(XAccount)
            .where(XAccount.workspace_id == post.workspace_id)
            .order_by(XAccount.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if row is None:
        raise PermanentPublishError("no connected X account")
    return row
