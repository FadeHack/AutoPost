"""Bluesky connect endpoints.

App-Password auth (not OAuth) — atproto Python SDK is still session-based
pre-1.0. The connect endpoint takes a `{handle, app_password}` body,
validates by attempting `Client.login()`, captures the resolved DID and
display name, and persists both Fernet-encrypted.

Why a POST endpoint instead of a redirect dance: there's no browser flow.
The frontend renders a small form, posts here, gets back a status payload.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.logging import get_logger
from app.core.security import encrypt
from app.db import get_session
from app.models import BlueskyAccount, User

router = APIRouter(prefix="/auth/bluesky", tags=["auth-bluesky"])
log = get_logger("api.auth_bluesky")


class ConnectRequest(BaseModel):
    handle: str = Field(min_length=3, max_length=255)
    # App password format is `xxxx-xxxx-xxxx-xxxx`. We don't enforce shape
    # server-side — atproto raises if invalid, which we surface as 400.
    app_password: str = Field(min_length=8, max_length=255)


class StatusResponse(BaseModel):
    connected: bool
    handle: str | None = None
    did: str | None = None
    display_name: str | None = None


def _validate_via_atproto(handle: str, app_password: str) -> tuple[str, str | None]:
    """Synchronously attempt `Client.login()`. Returns (did, display_name).
    Raises ValueError on auth failure with a redacted message."""
    from atproto import Client  # type: ignore[import-untyped]

    client = Client()
    try:
        profile = client.login(handle, app_password)
    except Exception as e:
        # Don't echo the raw error — it may contain sensitive details. Log
        # full message server-side, return a generic 400 to the caller.
        log.warning("bluesky.connect.failed", handle=handle, error=str(e)[:300])
        raise ValueError("invalid handle or app password") from e
    return profile.did, getattr(profile, "display_name", None)


@router.post("/connect", response_model=StatusResponse)
async def connect(
    body: ConnectRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> StatusResponse:
    """Validate the credentials with Bluesky, then store Fernet-encrypted.
    Upserts on `(user_id, handle)` so re-connecting with a rotated app
    password replaces the old row instead of erroring on the unique key."""
    try:
        did, display_name = await asyncio.to_thread(
            _validate_via_atproto, body.handle, body.app_password
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )

    stmt = (
        select(BlueskyAccount)
        .where(
            BlueskyAccount.user_id == user.id,
            BlueskyAccount.handle == body.handle,
        )
        .limit(1)
    )
    existing = (await session.execute(stmt)).scalars().first()
    if existing is not None:
        existing.app_password = encrypt(body.app_password)
        existing.did = did
        existing.display_name = display_name
    else:
        session.add(
            BlueskyAccount(
                user_id=user.id,
                handle=body.handle,
                did=did,
                app_password=encrypt(body.app_password),
                display_name=display_name,
            )
        )
    await session.commit()
    log.info("bluesky.connect.ok", handle=body.handle, did=did)
    return StatusResponse(
        connected=True,
        handle=body.handle,
        did=did,
        display_name=display_name,
    )


@router.get("/status", response_model=StatusResponse)
async def status_(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> StatusResponse:
    """Reports whether the dashboard user has a Bluesky account connected."""
    stmt = (
        select(BlueskyAccount)
        .where(BlueskyAccount.user_id == user.id)
        .order_by(BlueskyAccount.created_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return StatusResponse(connected=False)
    return StatusResponse(
        connected=True,
        handle=row.handle,
        did=row.did,
        display_name=row.display_name,
    )


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Remove every Bluesky account for the dashboard user. Idempotent."""
    stmt = select(BlueskyAccount).where(BlueskyAccount.user_id == user.id)
    rows = (await session.execute(stmt)).scalars().all()
    for r in rows:
        await session.delete(r)
    await session.commit()
    return None
