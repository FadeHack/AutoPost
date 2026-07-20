"""X (Twitter) OAuth endpoints — single fixed app, OAuth 2.0 Authorization Code
+ PKCE.

Mirrors the LinkedIn/Threads flow (`/start` returns an authorize URL the
frontend redirects to; `/callback` exchanges the code). The X-specific twist:
`/start` generates a PKCE `code_verifier`/`code_challenge`, carries the verifier
inside the encrypted `state`, and the callback pulls it back out to complete the
token exchange. The first token response already carries the rotating refresh
token (offline.access), so — unlike Threads — there's no separate long-lived
upgrade step.

Every route is gated on `PLATFORM_X_ENABLED`. The X API is paid (no free tier
for new developers), so the flow stays disabled until the operator provisions a
paid X app and sets its credentials.
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
from app.models.user import User
from app.models.x_account import XAccount
from app.publishing import x_oauth as xo

router = APIRouter(prefix="/auth/x", tags=["auth-x"])
log = get_logger("api.auth_x")


def _require_enabled() -> None:
    if not settings.PLATFORM_X_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="X publishing is disabled (PLATFORM_X_ENABLED=false).",
        )


class StartResponse(BaseModel):
    authorize_url: str


class StatusResponse(BaseModel):
    enabled: bool
    connected: bool
    username: str | None = None
    display_name: str | None = None
    expires_at: str | None = None


@router.get("/start", response_model=StartResponse)
async def start(user: User = Depends(get_current_user)) -> StartResponse:
    """Return the X authorize URL. Generates a PKCE pair and stashes the verifier
    in the encrypted state so the stateless callback can finish the exchange."""
    _require_enabled()
    verifier, challenge = xo.generate_pkce()
    state, _nonce = xo.encode_state(str(user.id), verifier)
    return StartResponse(
        authorize_url=xo.build_authorize_url(state, challenge)
    )


@router.get("/callback")
async def callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    """X redirects the browser here with ?code=&state=. We exchange the code +
    PKCE verifier for the access/refresh token pair, resolve the profile,
    persist, and bounce back to the dashboard."""
    frontend = settings.FRONTEND_BASE_URL.rstrip("/")

    if not settings.PLATFORM_X_ENABLED:
        return RedirectResponse(f"{frontend}/?x=error&message=disabled", 302)
    if error:
        log.warning("x.callback.error", error=error, description=error_description)
        return RedirectResponse(
            f"{frontend}/?x=error&message={error_description or error}", 302
        )
    if not code or not state:
        return RedirectResponse(
            f"{frontend}/?x=error&message=missing_code_or_state", 302
        )

    try:
        decoded = xo.decode_state(state)
    except xo.XOAuthError as e:
        log.warning("x.callback.state_invalid", error=str(e))
        return RedirectResponse(f"{frontend}/?x=error&message=invalid_state", 302)

    try:
        token = await xo.exchange_code(code, decoded.code_verifier)
        profile = await xo.fetch_profile(token.access_token)
    except xo.XOAuthError as e:
        log.error("x.callback.exchange_failed", error=str(e))
        return RedirectResponse(
            f"{frontend}/?x=error&message=token_exchange_failed", 302
        )

    user_uuid = _uuid.UUID(decoded.user_id)
    db_user = await session.get(User, user_uuid)
    if db_user is None:
        return RedirectResponse(f"{frontend}/?x=error&message=unknown_user", 302)
    existing = (
        await session.execute(
            select(XAccount).where(
                XAccount.user_id == user_uuid,
                XAccount.x_user_id == profile.x_user_id,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        existing = XAccount(
            user_id=user_uuid,
            workspace_id=db_user.workspace_id,
            x_user_id=profile.x_user_id,
            username=profile.username,
        )
        session.add(existing)

    existing.username = profile.username
    existing.display_name = profile.display_name
    existing.access_token = encrypt(token.access_token)
    existing.refresh_token = (
        encrypt(token.refresh_token) if token.refresh_token else None
    )
    existing.expires_at = token.expires_at

    await session.commit()
    log.info("x.connected", user_id=decoded.user_id, username=profile.username)
    return RedirectResponse(f"{frontend}/?x=connected", 302)


@router.get("/status", response_model=StatusResponse)
async def get_status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StatusResponse:
    if not settings.PLATFORM_X_ENABLED:
        return StatusResponse(enabled=False, connected=False)
    row = (
        await session.execute(
            select(XAccount)
            .where(XAccount.user_id == user.id)
            .order_by(XAccount.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return StatusResponse(enabled=True, connected=False)
    return StatusResponse(
        enabled=True,
        connected=True,
        username=row.username,
        display_name=row.display_name,
        expires_at=row.expires_at.isoformat() if row.expires_at else None,
    )


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Remove every X account for the dashboard user. Idempotent."""
    rows = (
        await session.execute(
            select(XAccount).where(XAccount.user_id == user.id)
        )
    ).scalars().all()
    for r in rows:
        await session.delete(r)
    await session.commit()
    return None
