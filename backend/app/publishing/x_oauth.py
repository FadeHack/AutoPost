"""X (Twitter) API v2 OAuth 2.0 client — Authorization Code + PKCE, no DB.

X uses a single fixed app (like LinkedIn/Threads), so this mirrors that shape:
one client_id/secret, a CSRF `state`, a code→token exchange. The twists that make
X different from every other platform here:

  * PKCE is mandatory. We generate a `code_verifier` per authorize request and
    send its S256 `code_challenge` in the authorize URL. The stateless callback
    needs the original verifier back for the token exchange, so we carry it
    inside the Fernet-encrypted `state` (same trick Mastodon uses for client
    creds) rather than persisting it.
  * Confidential client. Our app has a secret, so the token endpoint is called
    with HTTP Basic auth (`base64(client_id:client_secret)`), per X's OAuth2 spec
    for confidential clients.
  * Short-lived access token (~2h) + ROTATING refresh token. The token response
    carries `access_token`, `refresh_token`, `expires_in` (offline.access). Each
    refresh returns a NEW access token AND a NEW refresh token; the caller must
    persist both.

Web-verified against docs.x.com (2026-07):
  Authorize   GET  https://x.com/i/oauth2/authorize
  Token       POST https://api.x.com/2/oauth2/token   (authorization_code | refresh_token)
  Identity    GET  https://api.x.com/2/users/me
"""

from __future__ import annotations

import base64
import hashlib
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

AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
USERS_ME_URL = "https://api.x.com/2/users/me"


class XOAuthError(Exception):
    pass


@dataclass(frozen=True)
class XToken:
    access_token: str
    refresh_token: str | None
    expires_at: datetime


@dataclass(frozen=True)
class XProfile:
    x_user_id: str
    username: str
    display_name: str | None


# --- PKCE ---


def generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge). Verifier is 43-128 chars of
    URL-safe entropy; challenge is base64url(sha256(verifier)) with S256."""
    verifier = secrets.token_urlsafe(64)  # ~86 chars, within the 43-128 range
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# --- State (CSRF + carries the PKCE verifier) ---


def encode_state(user_id: str, code_verifier: str) -> tuple[str, str]:
    """Returns (state, nonce). The state carries the user + PKCE verifier so the
    stateless callback can complete the token exchange."""
    nonce = secrets.token_urlsafe(16)
    payload = json.dumps(
        {
            "u": user_id,
            "v": code_verifier,
            "n": nonce,
            "t": int(datetime.now(tz=timezone.utc).timestamp()),
        },
        separators=(",", ":"),
    )
    return encrypt(payload), nonce


@dataclass(frozen=True)
class DecodedState:
    user_id: str
    code_verifier: str
    nonce: str


def decode_state(state: str) -> DecodedState:
    """Raises XOAuthError if expired or tampered."""
    try:
        raw = decrypt_with_ttl(state, STATE_TTL_SECONDS)
        data = json.loads(raw)
        return DecodedState(
            user_id=str(data["u"]),
            code_verifier=str(data["v"]),
            nonce=str(data["n"]),
        )
    except Exception as e:
        raise XOAuthError(f"invalid or expired state: {e}") from e


# --- Authorize URL ---


def build_authorize_url(state: str, code_challenge: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.X_CLIENT_ID,
        "redirect_uri": settings.X_REDIRECT_URI,
        "scope": settings.X_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


# --- Token endpoint ---


def _basic_auth_header() -> dict[str, str]:
    raw = f"{settings.X_CLIENT_ID}:{settings.X_CLIENT_SECRET}".encode("ascii")
    return {"Authorization": f"Basic {base64.b64encode(raw).decode('ascii')}"}


def _token_from_body(body: dict) -> XToken:
    token = body.get("access_token")
    if not token:
        raise XOAuthError("token response carried no access_token")
    return XToken(
        access_token=token,
        refresh_token=body.get("refresh_token"),
        expires_at=_expiry_from(body.get("expires_in")),
    )


async def exchange_code(code: str, code_verifier: str) -> XToken:
    """POST /2/oauth2/token (grant_type=authorization_code) — exchange the auth
    code + PKCE verifier for the first access/refresh token pair."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(
            TOKEN_URL,
            headers=_basic_auth_header(),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.X_REDIRECT_URI,
                "code_verifier": code_verifier,
                "client_id": settings.X_CLIENT_ID,
            },
        )
    if r.status_code != 200:
        raise XOAuthError(f"code exchange failed: {r.status_code} {r.text[:300]}")
    return _token_from_body(r.json())


async def refresh_token(refresh_token_value: str) -> XToken:
    """POST /2/oauth2/token (grant_type=refresh_token). X rotates the refresh
    token, so the returned XToken carries a NEW refresh token — persist it."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(
            TOKEN_URL,
            headers=_basic_auth_header(),
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token_value,
                "client_id": settings.X_CLIENT_ID,
            },
        )
    if r.status_code != 200:
        raise XOAuthError(f"token refresh failed: {r.status_code} {r.text[:300]}")
    return _token_from_body(r.json())


async def fetch_profile(access_token: str) -> XProfile:
    """GET /2/users/me — resolve the connected account (id, username, name)."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(
            USERS_ME_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if r.status_code != 200:
        raise XOAuthError(f"profile fetch failed: {r.status_code} {r.text[:300]}")
    data = r.json().get("data") or {}
    if not data.get("id") or not data.get("username"):
        raise XOAuthError("profile fetch returned an incomplete profile")
    return XProfile(
        x_user_id=str(data["id"]),
        username=str(data["username"]),
        display_name=data.get("name") or None,
    )


def _expiry_from(expires_in: int | None) -> datetime:
    """X returns `expires_in` seconds (~7200 = 2h). Fall back to 2h if absent so
    the proactive-refresh logic always has a value to gate on."""
    seconds = int(expires_in) if expires_in else 2 * 3600
    return datetime.now(tz=timezone.utc) + timedelta(seconds=seconds)
