"""Mastodon OAuth 2.0 client — pure HTTP, no DB.

Mastodon is federated: there's no central app registry, so the OAuth client
must be registered dynamically per instance (`POST /api/v1/apps`) before the
authorize redirect. The returned `client_id`/`client_secret` are needed again
in the callback for the token exchange — we carry them through the Fernet-
encrypted `state` (TTL-checked) instead of persisting a `mastodon_apps` table.

Standard `read write` scopes. Access tokens don't expire by default and no
refresh token is issued, so there's no refresh path (mirrors the operational
reality of LinkedIn dev apps, for a different reason).
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse

import httpx

from app.config import settings
from app.core.security import decrypt_with_ttl, encrypt

STATE_TTL_SECONDS = 600  # 10 minutes
HTTP_TIMEOUT = 20.0


class MastodonOAuthError(Exception):
    pass


@dataclass(frozen=True)
class MastodonApp:
    client_id: str
    client_secret: str


@dataclass(frozen=True)
class MastodonProfile:
    account_id: str
    username: str
    acct: str
    display_name: str | None


# --- Instance normalization ---


def normalize_instance(raw: str) -> str:
    """Coerce user input (`mastodon.social`, `https://mastodon.social/`,
    `HACHYDERM.io`) into a canonical `https://host` origin. Raises on garbage."""
    if not raw or not raw.strip():
        raise MastodonOAuthError("instance is required")
    candidate = raw.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    host = (parsed.netloc or parsed.path).strip("/").lower()
    if not host or "." not in host or " " in host:
        raise MastodonOAuthError(f"invalid instance: {raw!r}")
    return f"https://{host}"


# --- State (CSRF + carries instance + client creds) ---


def encode_state(
    user_id: str, instance: str, client_id: str, client_secret: str
) -> tuple[str, str]:
    """Returns (state, nonce). The state carries everything the stateless
    callback needs: user, instance, and the per-instance client credentials."""
    nonce = secrets.token_urlsafe(16)
    payload = json.dumps(
        {
            "u": user_id,
            "i": instance,
            "ci": client_id,
            "cs": client_secret,
            "n": nonce,
            "t": int(datetime.now(tz=timezone.utc).timestamp()),
        },
        separators=(",", ":"),
    )
    return encrypt(payload), nonce


@dataclass(frozen=True)
class DecodedState:
    user_id: str
    instance: str
    client_id: str
    client_secret: str
    nonce: str


def decode_state(state: str) -> DecodedState:
    """Raises MastodonOAuthError if expired or tampered."""
    try:
        raw = decrypt_with_ttl(state, STATE_TTL_SECONDS)
        data = json.loads(raw)
        return DecodedState(
            user_id=str(data["u"]),
            instance=str(data["i"]),
            client_id=str(data["ci"]),
            client_secret=str(data["cs"]),
            nonce=str(data["n"]),
        )
    except Exception as e:
        raise MastodonOAuthError(f"invalid or expired state: {e}") from e


# --- HTTP calls ---


async def register_app(instance: str) -> MastodonApp:
    """POST /api/v1/apps — dynamically register an OAuth client on `instance`."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(
            f"{instance}/api/v1/apps",
            data={
                "client_name": settings.MASTODON_CLIENT_NAME,
                "redirect_uris": settings.MASTODON_REDIRECT_URI,
                "scopes": settings.MASTODON_SCOPES,
            },
        )
    if r.status_code != 200:
        raise MastodonOAuthError(
            f"app registration failed: {r.status_code} {r.text[:300]}"
        )
    body = r.json()
    if not body.get("client_id") or not body.get("client_secret"):
        raise MastodonOAuthError("app registration returned no client credentials")
    return MastodonApp(
        client_id=body["client_id"], client_secret=body["client_secret"]
    )


def build_authorize_url(instance: str, client_id: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": settings.MASTODON_REDIRECT_URI,
        "scope": settings.MASTODON_SCOPES,
        "state": state,
    }
    return f"{instance}/oauth/authorize?{urlencode(params)}"


async def exchange_code(
    instance: str, client_id: str, client_secret: str, code: str
) -> str:
    """POST /oauth/token — exchange the auth code for an access token."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(
            f"{instance}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": settings.MASTODON_REDIRECT_URI,
                "scope": settings.MASTODON_SCOPES,
            },
        )
    if r.status_code != 200:
        raise MastodonOAuthError(
            f"token exchange failed: {r.status_code} {r.text[:300]}"
        )
    token = r.json().get("access_token")
    if not token:
        raise MastodonOAuthError("token exchange returned no access_token")
    return token


async def verify_credentials(instance: str, access_token: str) -> MastodonProfile:
    """GET /api/v1/accounts/verify_credentials — resolve the connected account."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(
            f"{instance}/api/v1/accounts/verify_credentials",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if r.status_code != 200:
        raise MastodonOAuthError(
            f"verify_credentials failed: {r.status_code} {r.text[:300]}"
        )
    body = r.json()
    if not body.get("id") or not body.get("username"):
        raise MastodonOAuthError("verify_credentials returned an incomplete profile")
    return MastodonProfile(
        account_id=str(body["id"]),
        username=str(body["username"]),
        acct=str(body.get("acct") or body["username"]),
        display_name=body.get("display_name") or None,
    )
