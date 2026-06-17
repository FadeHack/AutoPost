"""Instagram OAuth 2.0 client (Instagram Login flow) — pure HTTP, no DB.

Uses Meta's **Instagram Login** flow (NOT Facebook Login) — the lightweight
single-fixed-app path that skips the legacy Facebook-Page link. Mirrors the
Threads OAuth shape (one client_id/secret, a CSRF `state`, code→short→long-lived
exchange). Web-verified against developers.facebook.com/docs/instagram-platform
(2026-06-16):

  Authorize       GET  https://www.instagram.com/oauth/authorize
  Code exchange   POST https://api.instagram.com/oauth/access_token   (short-lived, 1h)
  Long-lived      GET  https://graph.instagram.com/access_token        (ig_exchange_token, 60d)
  Refresh         GET  https://graph.instagram.com/refresh_access_token (ig_refresh_token, 60d)
  Profile         GET  https://graph.instagram.com/{ver}/me?fields=user_id,username,account_type

The long-lived token is what we persist; Instagram refreshes it **in place**
(no separate refresh_token), so the publisher refreshes proactively on staleness.
The short-lived code exchange returns the IG-scoped `user_id` directly, which is
the path segment used for publishing (`graph.instagram.com/{ver}/{user_id}/media`).
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.core.security import decrypt_with_ttl, encrypt

STATE_TTL_SECONDS = 600  # 10 minutes
HTTP_TIMEOUT = 20.0

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_EXCHANGE_URL = "https://api.instagram.com/oauth/access_token"
LONG_LIVED_URL = "https://graph.instagram.com/access_token"
REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
GRAPH_BASE = "https://graph.instagram.com"


class InstagramOAuthError(Exception):
    pass


@dataclass(frozen=True)
class ShortLivedToken:
    access_token: str
    instagram_user_id: str


@dataclass(frozen=True)
class LongLivedToken:
    access_token: str
    expires_at: datetime


@dataclass(frozen=True)
class InstagramProfile:
    instagram_user_id: str
    username: str
    account_type: str | None


# --- State (CSRF) ---


def encode_state(user_id: str) -> tuple[str, str]:
    """Returns (state, nonce). Fixed app, so state only carries the user +
    a nonce + timestamp (the TTL is enforced on decode)."""
    nonce = secrets.token_urlsafe(16)
    payload = json.dumps(
        {
            "u": user_id,
            "n": nonce,
            "t": int(datetime.now(tz=timezone.utc).timestamp()),
        },
        separators=(",", ":"),
    )
    return encrypt(payload), nonce


@dataclass(frozen=True)
class DecodedState:
    user_id: str
    nonce: str


def decode_state(state: str) -> DecodedState:
    """Raises InstagramOAuthError if expired or tampered."""
    try:
        raw = decrypt_with_ttl(state, STATE_TTL_SECONDS)
        data = json.loads(raw)
        return DecodedState(user_id=str(data["u"]), nonce=str(data["n"]))
    except Exception as e:
        raise InstagramOAuthError(f"invalid or expired state: {e}") from e


# --- Authorize URL ---


def build_authorize_url(state: str) -> str:
    params = {
        "client_id": settings.INSTAGRAM_APP_ID,
        "redirect_uri": settings.INSTAGRAM_REDIRECT_URI,
        "scope": settings.INSTAGRAM_SCOPES,
        "response_type": "code",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


# --- HTTP calls ---


def _token_from_body(body: dict) -> tuple[str | None, str | None]:
    """The Instagram Login code-exchange response has historically shipped two
    shapes: flat `{access_token, user_id}` and wrapped `{data: [{...}]}`. Handle
    both so a Meta response-format change doesn't break the connect flow."""
    if isinstance(body.get("data"), list) and body["data"]:
        first = body["data"][0]
        return first.get("access_token"), first.get("user_id")
    return body.get("access_token"), body.get("user_id")


async def exchange_code(code: str) -> ShortLivedToken:
    """POST /oauth/access_token — exchange the auth code for a SHORT-lived token.
    Returns the short-lived token + the IG-scoped user id (caller upgrades the
    token to long-lived)."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(
            TOKEN_EXCHANGE_URL,
            data={
                "client_id": settings.INSTAGRAM_APP_ID,
                "client_secret": settings.INSTAGRAM_APP_SECRET,
                "grant_type": "authorization_code",
                "redirect_uri": settings.INSTAGRAM_REDIRECT_URI,
                "code": code,
            },
        )
    if r.status_code != 200:
        raise InstagramOAuthError(
            f"code exchange failed: {r.status_code} {r.text[:300]}"
        )
    token, user_id = _token_from_body(r.json())
    if not token or not user_id:
        raise InstagramOAuthError(
            "code exchange returned no access_token / user_id"
        )
    return ShortLivedToken(access_token=token, instagram_user_id=str(user_id))


async def exchange_long_lived(short_token: str) -> LongLivedToken:
    """GET /access_token?grant_type=ig_exchange_token — upgrade a short-lived
    token to a 60-day long-lived one."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(
            LONG_LIVED_URL,
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": settings.INSTAGRAM_APP_SECRET,
                "access_token": short_token,
            },
        )
    if r.status_code != 200:
        raise InstagramOAuthError(
            f"long-lived exchange failed: {r.status_code} {r.text[:300]}"
        )
    body = r.json()
    token = body.get("access_token")
    if not token:
        raise InstagramOAuthError("long-lived exchange returned no access_token")
    return LongLivedToken(
        access_token=token,
        expires_at=_expiry_from(body.get("expires_in")),
    )


async def refresh_long_lived(long_token: str) -> LongLivedToken:
    """GET /refresh_access_token?grant_type=ig_refresh_token — refresh a
    long-lived token (must be ≥24h old, not expired). Returns a fresh 60-day
    token (in place — no separate refresh token)."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(
            REFRESH_URL,
            params={
                "grant_type": "ig_refresh_token",
                "access_token": long_token,
            },
        )
    if r.status_code != 200:
        raise InstagramOAuthError(
            f"token refresh failed: {r.status_code} {r.text[:300]}"
        )
    body = r.json()
    token = body.get("access_token")
    if not token:
        raise InstagramOAuthError("token refresh returned no access_token")
    return LongLivedToken(
        access_token=token,
        expires_at=_expiry_from(body.get("expires_in")),
    )


async def fetch_profile(access_token: str) -> InstagramProfile:
    """GET /{ver}/me?fields=user_id,username,account_type — resolve the account.

    Instagram Login returns the IG-scoped id under `user_id` (older Graph paths
    used `id`); accept either so the field rename doesn't break us."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(
            f"{GRAPH_BASE}/{settings.INSTAGRAM_API_VERSION}/me",
            params={
                "fields": "user_id,username,account_type",
                "access_token": access_token,
            },
        )
    if r.status_code != 200:
        raise InstagramOAuthError(
            f"profile fetch failed: {r.status_code} {r.text[:300]}"
        )
    body = r.json()
    ig_id = body.get("user_id") or body.get("id")
    if not ig_id or not body.get("username"):
        raise InstagramOAuthError("profile fetch returned an incomplete profile")
    return InstagramProfile(
        instagram_user_id=str(ig_id),
        username=str(body["username"]),
        account_type=body.get("account_type") or None,
    )


def _expiry_from(expires_in: int | None) -> datetime:
    """Instagram returns `expires_in` seconds (~60 days). Fall back to 60 days
    if absent so the dashboard's expiry surface always has a value."""
    seconds = int(expires_in) if expires_in else 60 * 24 * 3600
    return datetime.now(tz=timezone.utc) + timedelta(seconds=seconds)
