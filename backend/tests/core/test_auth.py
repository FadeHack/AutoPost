"""Access-gate unit tests (Phase 14 Chunk A).

The tool is invite-only: `get_current_user` must reject a valid Supabase token
whose email was never provisioned, JIT-provision only configured bootstrap admins,
and never auto-promote anyone else. `require_admin` gates the /admin panel.

No real DB — `session` is an AsyncMock and `_verify_supabase_jwt` is patched, matching
the repo's mock-first test convention.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.config import settings
from app.core import auth as auth_mod
from app.core.auth import AccessDeniedError, get_current_user, require_admin
from app.models.base import UserRole
from app.models.user import User

BOOTSTRAP = "boss@example.com"


def _creds() -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")


@pytest.fixture(autouse=True)
def _bootstrap_list(monkeypatch):
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAILS", BOOTSTRAP)


def _patch_jwt(monkeypatch, *, sub: str, email: str) -> None:
    monkeypatch.setattr(
        auth_mod,
        "_verify_supabase_jwt",
        AsyncMock(return_value={"sub": sub, "email": email}),
    )


def _mock_session(existing: User | None) -> AsyncMock:
    session = AsyncMock()
    session.get = AsyncMock(return_value=existing)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = lambda obj: None
    return session


@pytest.mark.asyncio
async def test_unprovisioned_email_is_denied(monkeypatch):
    _patch_jwt(monkeypatch, sub=str(uuid.uuid4()), email="stranger@example.com")
    session = _mock_session(existing=None)
    with pytest.raises(AccessDeniedError) as exc:
        await get_current_user(_creds(), session)
    assert exc.value.status_code == 403
    session.commit.assert_not_awaited()  # never provisions a stranger


@pytest.mark.asyncio
async def test_bootstrap_admin_is_jit_provisioned_as_admin(monkeypatch):
    uid = str(uuid.uuid4())
    _patch_jwt(monkeypatch, sub=uid, email=BOOTSTRAP.upper())  # case-insensitive
    session = _mock_session(existing=None)
    user = await get_current_user(_creds(), session)
    assert user.role is UserRole.admin
    assert str(user.id) == uid
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_bootstrap_admin_self_heals_if_demoted(monkeypatch):
    uid = uuid.uuid4()
    existing = User(id=uid, email=BOOTSTRAP, role=UserRole.editor)
    _patch_jwt(monkeypatch, sub=str(uid), email=BOOTSTRAP)
    session = _mock_session(existing=existing)
    user = await get_current_user(_creds(), session)
    assert user.role is UserRole.admin
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_existing_non_admin_is_not_promoted(monkeypatch):
    uid = uuid.uuid4()
    existing = User(id=uid, email="editor@example.com", role=UserRole.editor)
    _patch_jwt(monkeypatch, sub=str(uid), email="editor@example.com")
    session = _mock_session(existing=existing)
    user = await get_current_user(_creds(), session)
    assert user.role is UserRole.editor
    session.commit.assert_not_awaited()  # nothing changed


@pytest.mark.asyncio
async def test_existing_user_email_synced(monkeypatch):
    uid = uuid.uuid4()
    existing = User(id=uid, email="old@example.com", role=UserRole.editor)
    _patch_jwt(monkeypatch, sub=str(uid), email="new@example.com")
    session = _mock_session(existing=existing)
    user = await get_current_user(_creds(), session)
    assert user.email == "new@example.com"
    assert user.role is UserRole.editor
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_require_admin_allows_admin():
    admin = User(id=uuid.uuid4(), email="a@example.com", role=UserRole.admin)
    assert await require_admin(admin) is admin


@pytest.mark.asyncio
async def test_require_admin_blocks_editor():
    editor = User(id=uuid.uuid4(), email="e@example.com", role=UserRole.editor)
    with pytest.raises(AccessDeniedError) as exc:
        await require_admin(editor)
    assert exc.value.status_code == 403
