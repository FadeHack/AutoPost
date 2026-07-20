"""Admin API — Phase 14 Chunk F. Mock-session unit tests (no HTTP harness).

Covers approve (invite+provision, idempotent, existing-user skip), deny, direct
invite (dup guard, invite-failure → 502), role change (last-admin guard) and
revoke (self + last-admin guards). Supabase invite is monkeypatched — no network.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import admin as adm
from app.core.supabase_admin import SupabaseAdminError
from app.models.access_request import AccessRequest
from app.models.base import AccessRequestStatus, UserRole
from app.models.user import User
from app.models.workspace import Workspace


def _admin_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@nestwhirr.com",
        role=UserRole.admin,
        workspace_id=uuid.uuid4(),
    )


def _session(get_map: dict | None = None, scalar: object = None) -> AsyncMock:
    """Mock async session. `get_map` maps model class → object for `session.get`;
    `scalar` is what `execute(...).scalar_one_or_none()` returns."""
    s = AsyncMock()
    get_map = get_map or {}

    async def _get(model, _id):
        return get_map.get(model)

    s.get = AsyncMock(side_effect=_get)
    result = SimpleNamespace(
        scalar_one_or_none=lambda: scalar,
        scalar_one=lambda: 2,  # default admin_count > 1
    )
    s.execute = AsyncMock(return_value=result)
    s.add = lambda obj: None
    s.flush = AsyncMock()
    s.commit = AsyncMock()
    s.refresh = AsyncMock()
    s.delete = AsyncMock()
    return s


# --- approve ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_invites_and_provisions(monkeypatch):
    req = AccessRequest(id=uuid.uuid4(), email="New@Example.com", status=AccessRequestStatus.pending)
    session = _session(get_map={AccessRequest: req}, scalar=None)  # no existing user

    invited: list[str] = []

    async def fake_invite(email, *, redirect_to=None):
        invited.append(email)
        return uuid.uuid4()

    monkeypatch.setattr(adm, "invite_user_by_email", fake_invite)
    added: list = []
    session.add = added.append

    out = await approve_via(req.id, session)

    assert invited == ["new@example.com"]  # lowercased
    assert out.status == AccessRequestStatus.approved
    assert out.reviewed_at is not None
    # provisioned a Workspace + a User
    assert any(isinstance(o, Workspace) for o in added)
    assert any(isinstance(o, User) for o in added)


@pytest.mark.asyncio
async def test_approve_already_approved_is_noop(monkeypatch):
    req = AccessRequest(id=uuid.uuid4(), email="done@example.com", status=AccessRequestStatus.approved)
    session = _session(get_map={AccessRequest: req})

    async def fail_invite(*a, **k):  # must not be called
        raise AssertionError("should not re-invite")

    monkeypatch.setattr(adm, "invite_user_by_email", fail_invite)
    out = await approve_via(req.id, session)
    assert out is req
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_existing_user_skips_invite(monkeypatch):
    req = AccessRequest(id=uuid.uuid4(), email="known@example.com", status=AccessRequestStatus.pending)
    existing = User(id=uuid.uuid4(), email="known@example.com", role=UserRole.editor, workspace_id=uuid.uuid4())
    session = _session(get_map={AccessRequest: req}, scalar=existing)

    async def fail_invite(*a, **k):
        raise AssertionError("should not invite an existing user")

    monkeypatch.setattr(adm, "invite_user_by_email", fail_invite)
    out = await approve_via(req.id, session)
    assert out.status == AccessRequestStatus.approved


@pytest.mark.asyncio
async def test_approve_missing_request_404():
    session = _session(get_map={})  # get returns None
    with pytest.raises(HTTPException) as exc:
        await approve_via(uuid.uuid4(), session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_approve_invite_failure_502(monkeypatch):
    req = AccessRequest(id=uuid.uuid4(), email="boom@example.com", status=AccessRequestStatus.pending)
    session = _session(get_map={AccessRequest: req}, scalar=None)

    async def boom(*a, **k):
        raise SupabaseAdminError("supabase down")

    monkeypatch.setattr(adm, "invite_user_by_email", boom)
    with pytest.raises(HTTPException) as exc:
        await approve_via(req.id, session)
    assert exc.value.status_code == 502


# --- deny ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deny_marks_denied():
    req = AccessRequest(id=uuid.uuid4(), email="no@example.com", status=AccessRequestStatus.pending)
    session = _session(get_map={AccessRequest: req})
    admin = _admin_user()
    out = await adm.deny_access_request(req.id, admin, session)
    assert out.status == AccessRequestStatus.denied
    assert out.reviewed_by == admin.id


# --- direct invite ------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_invite_duplicate_409(monkeypatch):
    existing = User(id=uuid.uuid4(), email="dupe@example.com", role=UserRole.editor, workspace_id=uuid.uuid4())
    session = _session(scalar=existing)
    with pytest.raises(HTTPException) as exc:
        await adm.invite_user(adm.DirectInvite(email="dupe@example.com"), _admin_user(), session)
    assert exc.value.status_code == 409


# --- role change --------------------------------------------------------------


@pytest.mark.asyncio
async def test_demote_last_admin_blocked():
    target = User(id=uuid.uuid4(), email="solo@admin.com", role=UserRole.admin, workspace_id=uuid.uuid4())
    session = _session(get_map={User: target})
    session.execute.return_value = SimpleNamespace(scalar_one=lambda: 1, scalar_one_or_none=lambda: None)
    with pytest.raises(HTTPException) as exc:
        await adm.update_user(target.id, adm.UserUpdate(role=UserRole.editor), _admin_user(), session)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_role_change_succeeds():
    target = User(id=uuid.uuid4(), email="e@x.com", role=UserRole.editor, workspace_id=uuid.uuid4())
    session = _session(get_map={User: target})
    out = await adm.update_user(target.id, adm.UserUpdate(role=UserRole.viewer), _admin_user(), session)
    assert out.role == UserRole.viewer


# --- revoke -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_self_blocked():
    admin = _admin_user()
    session = _session()
    with pytest.raises(HTTPException) as exc:
        await adm.revoke_user(admin.id, admin, session)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_revoke_last_admin_blocked():
    target = User(id=uuid.uuid4(), email="last@admin.com", role=UserRole.admin, workspace_id=uuid.uuid4())
    ws = Workspace(id=target.workspace_id, name="last")
    session = _session(get_map={User: target, Workspace: ws})
    session.execute.return_value = SimpleNamespace(scalar_one=lambda: 1, scalar_one_or_none=lambda: None)
    with pytest.raises(HTTPException) as exc:
        await adm.revoke_user(target.id, _admin_user(), session)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_revoke_deletes_user_and_workspace():
    target = User(id=uuid.uuid4(), email="gone@example.com", role=UserRole.editor, workspace_id=uuid.uuid4())
    ws = Workspace(id=target.workspace_id, name="gone")
    session = _session(get_map={User: target, Workspace: ws})
    await adm.revoke_user(target.id, _admin_user(), session)
    deleted = [c.args[0] for c in session.delete.await_args_list]
    assert target in deleted
    assert ws in deleted


# --- helper: invoke approve with a fresh admin each call ----------------------


async def approve_via(request_id, session):
    return await adm.approve_access_request(request_id, _admin_user(), session)
