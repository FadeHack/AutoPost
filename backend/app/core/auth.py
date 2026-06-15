"""Supabase JWT verification + just-in-time User provisioning.

Modern Supabase projects use **asymmetric** signing keys (ECC P-256 / RSA / EdDSA).
We fetch the project's public JWKS once and cache it, then verify each token's
signature using the kid from its header.

(Legacy HS256 projects can still use `SUPABASE_JWT_SECRET` as a fallback — but new
tokens issued after a key rotation will be asymmetric, so this fallback is only
useful for in-flight legacy tokens during a migration window.)
"""

from __future__ import annotations

import asyncio
import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.db import get_session
from app.models.base import UserRole
from app.models.user import User

_bearer = HTTPBearer(auto_error=True)
log = get_logger("core.auth")

_ALGORITHMS = ["ES256", "RS256", "EdDSA"]


def _jwks_url() -> str:
    base = settings.SUPABASE_URL.rstrip("/")
    return f"{base}/auth/v1/.well-known/jwks.json"


_jwks_client: PyJWKClient | None = None


def _client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        if not settings.SUPABASE_URL:
            raise AuthError("SUPABASE_URL is not configured")
        _jwks_client = PyJWKClient(_jwks_url(), cache_keys=True, lifespan=3600)
    return _jwks_client


class AuthError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def _verify_supabase_jwt(token: str) -> dict:
    # PyJWKClient.get_signing_key_from_jwt is sync (does HTTP on first call, then cached).
    # Wrap in to_thread so we never block the event loop.
    try:
        signing_key = await asyncio.to_thread(
            lambda: _client().get_signing_key_from_jwt(token).key
        )
    except jwt.exceptions.PyJWKClientError as e:
        # If asymmetric lookup fails, optionally fall back to HS256 (legacy projects).
        if settings.SUPABASE_JWT_SECRET:
            log.warning("auth.jwks_failed_falling_back_to_hs256", error=str(e))
            return _verify_hs256(token)
        raise AuthError(f"unable to fetch signing key: {e}") from e

    try:
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=_ALGORITHMS,
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise AuthError("token expired") from e
    except jwt.InvalidAudienceError as e:
        raise AuthError("invalid audience") from e
    except jwt.InvalidTokenError as e:
        raise AuthError(f"invalid token: {e}") from e
    return payload


def _verify_hs256(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise AuthError("token expired") from e
    except jwt.InvalidTokenError as e:
        raise AuthError(f"invalid token (hs256 fallback): {e}") from e


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    """FastAPI dependency. Verifies the bearer token and returns the local `User` row,
    creating it on first sight (JIT provisioning)."""
    payload = await _verify_supabase_jwt(credentials.credentials)
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as e:
        raise AuthError("invalid sub claim") from e

    email = payload.get("email") or f"{user_id}@unknown"

    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id, email=email, role=UserRole.admin)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    elif user.email != email:
        user.email = email
        await session.commit()
        await session.refresh(user)

    return user
