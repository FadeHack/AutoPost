"""Mastodon OAuth endpoints (federated — per-instance dynamic app registration).

Unlike LinkedIn (one fixed dev app), each Mastodon instance is independent.
`/start` takes the instance the user wants to post to, registers an OAuth client
on it (`POST /api/v1/apps`), and returns the authorize URL. The client
credentials ride along inside the Fernet-encrypted `state` so the callback is
stateless. Bluesky uses App Password (no OAuth) — Mastodon is the first platform
to need a redirect dance besides LinkedIn.
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
from app.models.mastodon_account import MastodonAccount
from app.models.user import User
from app.publishing import mastodon_oauth as mo

router = APIRouter(prefix="/auth/mastodon", tags=["auth-mastodon"])
log = get_logger("api.auth_mastodon")


class StartResponse(BaseModel):
    authorize_url: str


class StatusResponse(BaseModel):
    connected: bool
    instance_url: str | None = None
    handle: str | None = None
    display_name: str | None = None


@router.get("/start", response_model=StartResponse)
async def start(
    instance: str = Query(..., description="Mastodon instance, e.g. mastodon.social"),
    user: User = Depends(get_current_user),
) -> StartResponse:
    """Register an OAuth app on the instance and return its authorize URL.
    The frontend redirects the browser to it."""
    try:
        norm = mo.normalize_instance(instance)
        app = await mo.register_app(norm)
    except mo.MastodonOAuthError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    state, _nonce = mo.encode_state(
        str(user.id), norm, app.client_id, app.client_secret
    )
    return StartResponse(
        authorize_url=mo.build_authorize_url(norm, app.client_id, state)
    )


@router.get("/callback")
async def callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    """Mastodon redirects the browser here with ?code=&state=. We exchange the
    code, resolve the account, persist it, and bounce back to the dashboard."""
    frontend = settings.FRONTEND_BASE_URL.rstrip("/")

    if error:
        log.warning("mastodon.callback.error", error=error, description=error_description)
        return RedirectResponse(
            f"{frontend}/?mastodon=error&message={error_description or error}", 302
        )
    if not code or not state:
        return RedirectResponse(
            f"{frontend}/?mastodon=error&message=missing_code_or_state", 302
        )

    try:
        decoded = mo.decode_state(state)
    except mo.MastodonOAuthError as e:
        log.warning("mastodon.callback.state_invalid", error=str(e))
        return RedirectResponse(f"{frontend}/?mastodon=error&message=invalid_state", 302)

    try:
        access_token = await mo.exchange_code(
            decoded.instance, decoded.client_id, decoded.client_secret, code
        )
        profile = await mo.verify_credentials(decoded.instance, access_token)
    except mo.MastodonOAuthError as e:
        log.error("mastodon.callback.exchange_failed", error=str(e))
        return RedirectResponse(
            f"{frontend}/?mastodon=error&message=token_exchange_failed", 302
        )

    user_uuid = _uuid.UUID(decoded.user_id)
    db_user = await session.get(User, user_uuid)
    if db_user is None:
        return RedirectResponse(f"{frontend}/?mastodon=error&message=unknown_user", 302)
    existing = (
        await session.execute(
            select(MastodonAccount).where(
                MastodonAccount.user_id == user_uuid,
                MastodonAccount.instance_url == decoded.instance,
                MastodonAccount.handle == profile.username,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        existing = MastodonAccount(
            user_id=user_uuid,
            workspace_id=db_user.workspace_id,
            instance_url=decoded.instance,
            handle=profile.username,
        )
        session.add(existing)

    existing.account_id = profile.account_id
    existing.access_token = encrypt(access_token)
    existing.display_name = profile.display_name

    await session.commit()
    log.info(
        "mastodon.connected",
        user_id=decoded.user_id,
        instance=decoded.instance,
        handle=profile.username,
    )
    return RedirectResponse(f"{frontend}/?mastodon=connected", 302)


@router.get("/status", response_model=StatusResponse)
async def get_status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StatusResponse:
    row = (
        await session.execute(
            select(MastodonAccount)
            .where(MastodonAccount.user_id == user.id)
            .order_by(MastodonAccount.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return StatusResponse(connected=False)
    return StatusResponse(
        connected=True,
        instance_url=row.instance_url,
        handle=row.handle,
        display_name=row.display_name,
    )


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Remove every Mastodon account for the dashboard user. Idempotent."""
    rows = (
        await session.execute(
            select(MastodonAccount).where(MastodonAccount.user_id == user.id)
        )
    ).scalars().all()
    for r in rows:
        await session.delete(r)
    await session.commit()
    return None
