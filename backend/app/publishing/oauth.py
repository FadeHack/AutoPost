"""LinkedIn OAuth 2.0 + OpenID Connect client.

Single dev app, scopes `openid profile email w_member_social`. The publisher uses the
authenticated member's OIDC `sub` claim (stored as `linkedin_accounts.member_sub`) to
build the author URN `urn:li:person:<sub>`.

State protection: the OAuth `state` parameter is a Fernet-encrypted JSON blob of
{u: user_id, n: nonce, t: timestamp}. Verified + TTL-checked on callback.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.core.security import decrypt_with_ttl, encrypt

LINKEDIN_AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

STATE_TTL_SECONDS = 600  # 10 minutes


class OAuthError(Exception):
    pass


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    expires_in: int
    refresh_token: str | None
    refresh_token_expires_in: int | None
    id_token: str | None
    scope: str

    @property
    def expires_at(self) -> datetime:
        return datetime.now(tz=timezone.utc).replace(microsecond=0) + _seconds(self.expires_in)


@dataclass(frozen=True)
class UserInfo:
    """OIDC userinfo claims. `sub` is the stable LinkedIn member identifier; used as
    the suffix of the personal author URN."""
    sub: str
    name: str | None
    email: str | None
    picture: str | None


def _seconds(n: int):
    from datetime import timedelta
    return timedelta(seconds=n)


# --- State (CSRF protection) ---


def encode_state(user_id: str) -> tuple[str, str]:
    """Returns (state, nonce). Both must be sent to LinkedIn and stored client-side
    in the URL only — server validates them on callback via Fernet decrypt + TTL."""
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


def decode_state(state: str) -> tuple[str, str]:
    """Returns (user_id, nonce). Raises OAuthError if expired or tampered."""
    try:
        raw = decrypt_with_ttl(state, STATE_TTL_SECONDS)
        data = json.loads(raw)
        return str(data["u"]), str(data["n"])
    except Exception as e:
        raise OAuthError(f"invalid or expired state: {e}") from e


# --- URL building ---


def build_authorize_url(state: str, nonce: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.LINKEDIN_CLIENT_ID,
        "redirect_uri": settings.LINKEDIN_REDIRECT_URI,
        "state": state,
        "scope": " ".join(settings.linkedin_scope_list),
        "nonce": nonce,
    }
    return f"{LINKEDIN_AUTHORIZE_URL}?{urlencode(params)}"


# --- HTTP calls ---


async def exchange_code(code: str) -> TokenResponse:
    """POST /accessToken — exchange auth code for tokens."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            LINKEDIN_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.LINKEDIN_REDIRECT_URI,
                "client_id": settings.LINKEDIN_CLIENT_ID,
                "client_secret": settings.LINKEDIN_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if r.status_code != 200:
        raise OAuthError(f"token exchange failed: {r.status_code} {r.text}")
    body = r.json()
    return TokenResponse(
        access_token=body["access_token"],
        expires_in=int(body["expires_in"]),
        refresh_token=body.get("refresh_token"),
        refresh_token_expires_in=body.get("refresh_token_expires_in"),
        id_token=body.get("id_token"),
        scope=body.get("scope", ""),
    )


async def refresh_token(refresh_token: str) -> TokenResponse:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            LINKEDIN_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.LINKEDIN_CLIENT_ID,
                "client_secret": settings.LINKEDIN_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if r.status_code != 200:
        raise OAuthError(f"token refresh failed: {r.status_code} {r.text}")
    body = r.json()
    return TokenResponse(
        access_token=body["access_token"],
        expires_in=int(body["expires_in"]),
        refresh_token=body.get("refresh_token", refresh_token),
        refresh_token_expires_in=body.get("refresh_token_expires_in"),
        id_token=body.get("id_token"),
        scope=body.get("scope", ""),
    )


async def fetch_userinfo(access_token: str) -> UserInfo:
    """GET /v2/userinfo — OIDC userinfo. Use the returned `sub` as the personal URN suffix."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(
            LINKEDIN_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if r.status_code != 200:
        raise OAuthError(f"userinfo failed: {r.status_code} {r.text}")
    body = r.json()
    return UserInfo(
        sub=body["sub"],
        name=body.get("name"),
        email=body.get("email"),
        picture=body.get("picture"),
    )
