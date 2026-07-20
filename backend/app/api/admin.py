"""Admin API — the invite-only control surface (Phase 14 Chunk F).

Every route is gated by `require_admin` (admin role, else 403). Powers the
`/admin` panel (Chunk G):

  * review the public access-request queue → approve (invite + provision) or deny
  * manage users → change role / revoke access
  * optionally invite someone directly (no prior request)

Approve/invite go through Supabase Auth admin (`invite_user_by_email`) to mail a
magic-link, then pre-provision the local `users`+`workspaces` rows keyed by the
returned Supabase UUID so the invitee's first-login JIT path recognizes them.
Newly invited users are ALWAYS `editor` — admin is granted only via the explicit
role-change endpoint here (or the bootstrap-admin config).
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import provision_workspace_and_user, require_admin
from app.core.logging import get_logger
from app.core.supabase_admin import SupabaseAdminError, invite_user_by_email
from app.db import get_session
from app.models.access_request import AccessRequest
from app.models.base import AccessRequestStatus, UserRole
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])
log = get_logger("api.admin")


# --- schemas ------------------------------------------------------------------


class AccessRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str | None
    company: str | None
    reason: str | None
    status: AccessRequestStatus
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: UUID | None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: UserRole
    workspace_id: UUID
    created_at: datetime


class UserUpdate(BaseModel):
    role: UserRole


class DirectInvite(BaseModel):
    email: str = Field(max_length=320)


# --- access-request queue -----------------------------------------------------


@router.get("/access-requests", response_model=list[AccessRequestRead])
async def list_access_requests(
    status_filter: AccessRequestStatus | None = Query(default=None, alias="status"),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[AccessRequest]:
    """List access requests, newest first. `?status=pending` scopes the queue."""
    stmt = select(AccessRequest).order_by(AccessRequest.created_at.desc())
    if status_filter is not None:
        stmt = stmt.where(AccessRequest.status == status_filter)
    return list((await session.execute(stmt)).scalars().all())


async def _load_request(session: AsyncSession, request_id: UUID) -> AccessRequest:
    req = await session.get(AccessRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="access request not found")
    return req


@router.post("/access-requests/{request_id}/approve", response_model=AccessRequestRead)
async def approve_access_request(
    request_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AccessRequest:
    """Approve a pending request: send the Supabase magic-link invite, provision
    the local user + workspace (role `editor`), and stamp the request approved.

    Idempotent-ish: a request already `approved` is returned unchanged (no second
    invite). Denied requests can still be approved (an admin changing their mind).
    """
    req = await _load_request(session, request_id)
    if req.status == AccessRequestStatus.approved:
        return req  # already handled — don't re-invite

    email = req.email.lower().strip()

    # If a local user already exists for this email (e.g. re-approve after a manual
    # provision), skip the invite and just close out the request.
    existing_user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    if existing_user is None:
        try:
            supabase_user_id = await invite_user_by_email(
                email, redirect_to=settings.FRONTEND_BASE_URL.rstrip("/")
            )
        except SupabaseAdminError as e:
            log.error("admin.approve.invite_failed", email=email, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Supabase invite failed: {e}",
            ) from e
        await provision_workspace_and_user(
            session, user_id=supabase_user_id, email=email, role=UserRole.editor
        )

    req.status = AccessRequestStatus.approved
    req.reviewed_at = datetime.now(timezone.utc)
    req.reviewed_by = admin.id
    await session.commit()
    await session.refresh(req)
    log.info("admin.access_request.approved", email=email, admin=str(admin.id))
    return req


@router.post("/access-requests/{request_id}/deny", response_model=AccessRequestRead)
async def deny_access_request(
    request_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AccessRequest:
    """Deny a request. No Supabase side effect — just marks it denied for audit."""
    req = await _load_request(session, request_id)
    req.status = AccessRequestStatus.denied
    req.reviewed_at = datetime.now(timezone.utc)
    req.reviewed_by = admin.id
    await session.commit()
    await session.refresh(req)
    log.info("admin.access_request.denied", email=req.email, admin=str(admin.id))
    return req


# --- direct invite (no prior request) ----------------------------------------


@router.post("/users/invite", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def invite_user(
    payload: DirectInvite,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Invite someone directly, bypassing the request queue (role `editor`)."""
    email = payload.email.lower().strip()
    existing = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="a user with this email already exists")

    try:
        supabase_user_id = await invite_user_by_email(
            email, redirect_to=settings.FRONTEND_BASE_URL.rstrip("/")
        )
    except SupabaseAdminError as e:
        log.error("admin.invite.failed", email=email, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Supabase invite failed: {e}",
        ) from e

    user = await provision_workspace_and_user(
        session, user_id=supabase_user_id, email=email, role=UserRole.editor
    )
    await session.commit()
    await session.refresh(user)
    log.info("admin.user.invited", email=email)
    return user


# --- user management ----------------------------------------------------------


@router.get("/users", response_model=list[UserRead])
async def list_users(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[User]:
    """List all users, newest first."""
    stmt = select(User).order_by(User.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Change a user's role. Guards against an admin locking everyone out by
    demoting the last remaining admin (including themselves)."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    if user.role == UserRole.admin and payload.role != UserRole.admin:
        admin_count = (
            await session.execute(
                select(func.count()).select_from(User).where(User.role == UserRole.admin)
            )
        ).scalar_one()
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="cannot demote the last remaining admin",
            )

    user.role = payload.role
    await session.commit()
    await session.refresh(user)
    log.info(
        "admin.user.role_changed",
        user=str(user.id),
        role=payload.role.value,
        admin=str(admin.id),
    )
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_user(
    user_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Hard-revoke: delete the local user + their workspace (cascading posts and
    connected accounts). Their next request is denied by the invite-only JIT gate.

    Guards: an admin can't revoke themselves, nor the last remaining admin. Note:
    the Supabase Auth identity persists (harmless — JIT denies it with no local
    row); a re-invite of the same email reuses it.
    """
    if user_id == admin.id:
        raise HTTPException(status_code=409, detail="you cannot revoke your own access")

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    if user.role == UserRole.admin:
        admin_count = (
            await session.execute(
                select(func.count()).select_from(User).where(User.role == UserRole.admin)
            )
        ).scalar_one()
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="cannot revoke the last remaining admin",
            )

    workspace_id = user.workspace_id
    await session.delete(user)  # delete-orphan cascades connected accounts
    await session.flush()
    # Now the workspace has no owning user (users.workspace_id is RESTRICT) — drop
    # it; CASCADE clears its posts and any remaining scoped rows.
    from app.models.workspace import Workspace

    workspace = await session.get(Workspace, workspace_id)
    if workspace is not None:
        await session.delete(workspace)
    await session.commit()
    log.info("admin.user.revoked", user=str(user_id), admin=str(admin.id))
    return None
