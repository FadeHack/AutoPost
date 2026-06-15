"""LinkedIn OAuth endpoints (member posting, single dev app)."""

from __future__ import annotations

from datetime import datetime, timezone

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
from app.models.base import AccountKind
from app.models.linkedin_account import LinkedInAccount
from app.models.user import User
from app.publishing import oauth

router = APIRouter(prefix="/auth/linkedin", tags=["auth-linkedin"])
log = get_logger("api.auth_linkedin")


class StartResponse(BaseModel):
    authorize_url: str


class StatusResponse(BaseModel):
    connected: bool
    account_kind: str | None = None
    display_name: str | None = None
    expires_at: datetime | None = None


@router.get("/start", response_model=StartResponse)
async def start(user: User = Depends(get_current_user)) -> StartResponse:
    """Returns the LinkedIn authorize URL. The frontend redirects the browser to it."""
    if not settings.LINKEDIN_CLIENT_ID or not settings.LINKEDIN_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LinkedIn OAuth is not configured",
        )
    state, nonce = oauth.encode_state(str(user.id))
    return StartResponse(authorize_url=oauth.build_authorize_url(state, nonce))


@router.get("/callback")
async def callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    """LinkedIn redirects the user's browser here with ?code=&state= on success.
    On failure, with ?error=&error_description=. We always redirect back to the frontend."""
    frontend = settings.FRONTEND_BASE_URL.rstrip("/")

    if error:
        log.warning("linkedin.callback.error", error=error, description=error_description)
        return RedirectResponse(
            f"{frontend}/?linkedin=error&message={error_description or error}",
            status_code=302,
        )
    if not code or not state:
        return RedirectResponse(f"{frontend}/?linkedin=error&message=missing_code_or_state", 302)

    try:
        user_id, _nonce = oauth.decode_state(state)
    except oauth.OAuthError as e:
        log.warning("linkedin.callback.state_invalid", error=str(e))
        return RedirectResponse(f"{frontend}/?linkedin=error&message=invalid_state", 302)

    try:
        tokens = await oauth.exchange_code(code)
    except oauth.OAuthError as e:
        log.error("linkedin.callback.token_exchange_failed", error=str(e))
        return RedirectResponse(f"{frontend}/?linkedin=error&message=token_exchange_failed", 302)

    try:
        userinfo = await oauth.fetch_userinfo(tokens.access_token)
    except oauth.OAuthError as e:
        log.error("linkedin.callback.userinfo_failed", error=str(e))
        return RedirectResponse(f"{frontend}/?linkedin=error&message=userinfo_failed", 302)

    # Upsert linkedin_account for (user_id, account_kind='personal').
    import uuid as _uuid

    user_uuid = _uuid.UUID(user_id)
    existing = await session.execute(
        select(LinkedInAccount).where(
            LinkedInAccount.user_id == user_uuid,
            LinkedInAccount.account_kind == AccountKind.personal,
        )
    )
    account = existing.scalar_one_or_none()

    if account is None:
        account = LinkedInAccount(
            user_id=user_uuid,
            account_kind=AccountKind.personal,
        )
        session.add(account)

    account.member_sub = userinfo.sub
    account.display_name = userinfo.name
    account.access_token = encrypt(tokens.access_token)
    account.refresh_token = encrypt(tokens.refresh_token) if tokens.refresh_token else None
    account.expires_at = tokens.expires_at
    account.scopes = [s for s in tokens.scope.split(" ") if s]

    await session.commit()
    log.info("linkedin.connected", user_id=user_id, member_sub=userinfo.sub, name=userinfo.name)

    return RedirectResponse(f"{frontend}/?linkedin=connected", 302)


@router.get("/status", response_model=StatusResponse)
async def get_status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StatusResponse:
    result = await session.execute(
        select(LinkedInAccount)
        .where(LinkedInAccount.user_id == user.id)
        .order_by(LinkedInAccount.updated_at.desc())
        .limit(1)
    )
    account = result.scalar_one_or_none()
    if account is None:
        return StatusResponse(connected=False)
    return StatusResponse(
        connected=True,
        account_kind=account.account_kind.value,
        display_name=account.display_name,
        expires_at=account.expires_at,
    )
