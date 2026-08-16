"""`/me` — identity/role/workspace read + workspace rename. Mock-session unit
tests (no HTTP harness), same convention as `test_admin.py`."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import me as me_api
from app.models.base import UserRole
from app.models.user import User
from app.models.workspace import Workspace


def _user(workspace_id: uuid.UUID) -> User:
    return User(
        id=uuid.uuid4(),
        email="operator@nestwhirr.com",
        role=UserRole.editor,
        workspace_id=workspace_id,
    )


def _session(workspace: Workspace | None) -> AsyncMock:
    s = AsyncMock()
    s.get = AsyncMock(return_value=workspace)
    s.commit = AsyncMock()
    s.refresh = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_read_me_returns_workspace_name():
    ws_id = uuid.uuid4()
    workspace = Workspace(id=ws_id, name="Nestwhirr")
    user = _user(ws_id)
    session = _session(workspace)

    out = await me_api.read_me(user=user, session=session)

    assert out.workspace_id == ws_id
    assert out.workspace_name == "Nestwhirr"
    assert out.role == UserRole.editor


@pytest.mark.asyncio
async def test_read_me_missing_workspace_404s():
    user = _user(uuid.uuid4())
    session = _session(None)

    with pytest.raises(HTTPException) as exc:
        await me_api.read_me(user=user, session=session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_rename_workspace_updates_and_trims():
    ws_id = uuid.uuid4()
    workspace = Workspace(id=ws_id, name="shivam")
    user = _user(ws_id)
    session = _session(workspace)

    out = await me_api.rename_workspace(
        me_api.WorkspaceRename(name="  Nestwhirr  "), user=user, session=session
    )

    assert workspace.name == "Nestwhirr"
    assert out.workspace_name == "Nestwhirr"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_rename_workspace_rejects_blank():
    ws_id = uuid.uuid4()
    workspace = Workspace(id=ws_id, name="shivam")
    user = _user(ws_id)
    session = _session(workspace)

    with pytest.raises(HTTPException) as exc:
        await me_api.rename_workspace(
            me_api.WorkspaceRename(name="   "), user=user, session=session
        )
    assert exc.value.status_code == 422
    assert workspace.name == "shivam"  # untouched
