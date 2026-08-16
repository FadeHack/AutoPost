"""Current-user endpoint — lets the frontend gate on identity + role (e.g. show the
/admin nav entry only to admins), know which workspace it's operating in, and
rename that workspace (the display name shown in the BrandSwitcher)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db import get_session
from app.models import User
from app.models.base import UserRole
from app.models.workspace import Workspace

router = APIRouter(prefix="/me", tags=["me"])


class MeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: UserRole
    workspace_id: UUID
    workspace_name: str


class WorkspaceRename(BaseModel):
    name: str = Field(min_length=1, max_length=255)


async def _load_own_workspace(session: AsyncSession, user: User) -> Workspace:
    # One user per workspace today (Phase 14) — `user.workspace_id` IS the
    # ownership check, no separate membership lookup needed yet.
    workspace = await session.get(Workspace, user.workspace_id)
    if workspace is None:
        # Should not happen — `workspace_id` is a NOT-NULL FK — but fail loudly
        # rather than silently fabricating a row.
        raise HTTPException(status_code=404, detail="workspace not found")
    return workspace


def _to_me_read(user: User, workspace: Workspace) -> MeRead:
    return MeRead(
        id=user.id,
        email=user.email,
        role=user.role,
        workspace_id=user.workspace_id,
        workspace_name=workspace.name,
    )


@router.get("", response_model=MeRead)
async def read_me(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MeRead:
    # `User.workspace` is a lazy relationship and `user` here was loaded via a bare
    # `session.get`, so a direct load-by-id avoids a MissingGreenlet in the async
    # context.
    workspace = await _load_own_workspace(session, user)
    return _to_me_read(user, workspace)


@router.patch("/workspace", response_model=MeRead)
async def rename_workspace(
    body: WorkspaceRename,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MeRead:
    """Rename the caller's own workspace (the BrandSwitcher display name).
    Any role can rename their own workspace — this is display metadata, not a
    tenant-isolation-sensitive write, and there's exactly one workspace to own
    per user today."""
    workspace = await _load_own_workspace(session, user)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name cannot be blank")
    workspace.name = name
    await session.commit()
    await session.refresh(workspace)
    return _to_me_read(user, workspace)
