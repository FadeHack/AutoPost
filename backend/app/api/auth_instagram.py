"""Instagram OAuth endpoints (Meta-gated — Instagram Login flow, single app).

Mirrors the Threads flow (`/start` returns an authorize URL the frontend
redirects to; `/callback` exchanges the code). Uses Meta's **Instagram Login**
flow (NOT Facebook Login) — the lightweight path that skips the Facebook-Page
link. Instagram issues a short-lived token (plus the IG-scoped user id) that we
immediately upgrade to a 60-day long-lived one before persisting.

Every route is gated on `PLATFORM_INSTAGRAM_ENABLED` — until Meta App Review
clears the content-publish scopes, the connect flow returns 503 and the
frontend hides the section.
"""

from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import get_current_user
from app.core.logging import get_logger
from app.core.security import encrypt
from app.db import get_session
from app.models.instagram_account import InstagramAccount
from app.models.user import User
from app.publishing import instagram_oauth as io

router = APIRouter(prefix="/auth/instagram", tags=["auth-instagram"])
log = get_logger("api.auth_instagram")


def _require_enabled() -> None:
    if not settings.PLATFORM_INSTAGRAM_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Instagram publishing is disabled (PLATFORM_INSTAGRAM_ENABLED=false).",
        )


class StartResponse(BaseModel):
    authorize_url: str


class StatusResponse(BaseModel):
    enabled: bool
    connected: bool
    username: str | None = None
    account_type: str | None = None
    expires_at: str | None = None


@router.get("/start", response_model=StartResponse)
async def start(user: User = Depends(get_current_user)) -> StartResponse:
    """Return the Instagram authorize URL. The frontend redirects to it."""
    _require_enabled()
    state, _nonce = io.encode_state(str(user.id))
    return StartResponse(authorize_url=io.build_authorize_url(state))


@router.get("/callback")
async def callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    """Meta redirects the browser here with ?code=&state=. We exchange the code
    for a short-lived token (+ IG user id), upgrade to long-lived, resolve the
    profile, persist, and bounce back to the dashboard."""
    frontend = settings.FRONTEND_BASE_URL.rstrip("/")

    if not settings.PLATFORM_INSTAGRAM_ENABLED:
        return RedirectResponse(f"{frontend}/?instagram=error&message=disabled", 302)
    if error:
        log.warning("instagram.callback.error", error=error, description=error_description)
        return RedirectResponse(
            f"{frontend}/?instagram=error&message={error_description or error}", 302
        )
    if not code or not state:
        return RedirectResponse(
            f"{frontend}/?instagram=error&message=missing_code_or_state", 302
        )

    try:
        decoded = io.decode_state(state)
    except io.InstagramOAuthError as e:
        log.warning("instagram.callback.state_invalid", error=str(e))
        return RedirectResponse(f"{frontend}/?instagram=error&message=invalid_state", 302)

    try:
        short = await io.exchange_code(code)
        long_lived = await io.exchange_long_lived(short.access_token)
        profile = await io.fetch_profile(long_lived.access_token)
    except io.InstagramOAuthError as e:
        log.error("instagram.callback.exchange_failed", error=str(e))
        return RedirectResponse(
            f"{frontend}/?instagram=error&message=token_exchange_failed", 302
        )

    user_uuid = _uuid.UUID(decoded.user_id)
    existing = (
        await session.execute(
            select(InstagramAccount).where(
                InstagramAccount.user_id == user_uuid,
                InstagramAccount.instagram_user_id == profile.instagram_user_id,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        existing = InstagramAccount(
            user_id=user_uuid,
            instagram_user_id=profile.instagram_user_id,
            username=profile.username,
        )
        session.add(existing)

    existing.username = profile.username
    existing.account_type = profile.account_type
    existing.access_token = encrypt(long_lived.access_token)
    existing.expires_at = long_lived.expires_at

    await session.commit()
    log.info(
        "instagram.connected",
        user_id=decoded.user_id,
        username=profile.username,
    )
    return RedirectResponse(f"{frontend}/?instagram=connected", 302)


@router.get("/status", response_model=StatusResponse)
async def get_status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StatusResponse:
    if not settings.PLATFORM_INSTAGRAM_ENABLED:
        return StatusResponse(enabled=False, connected=False)
    row = (
        await session.execute(
            select(InstagramAccount)
            .where(InstagramAccount.user_id == user.id)
            .order_by(InstagramAccount.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return StatusResponse(enabled=True, connected=False)
    return StatusResponse(
        enabled=True,
        connected=True,
        username=row.username,
        account_type=row.account_type,
        expires_at=row.expires_at.isoformat() if row.expires_at else None,
    )


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Remove every Instagram account for the dashboard user. Idempotent."""
    rows = (
        await session.execute(
            select(InstagramAccount).where(InstagramAccount.user_id == user.id)
        )
    ).scalars().all()
    for r in rows:
        await session.delete(r)
    await session.commit()
    return None
