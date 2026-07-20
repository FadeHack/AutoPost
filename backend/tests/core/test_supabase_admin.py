"""Supabase Auth admin wrapper — Phase 14 Chunk F. Mocks the sync SDK client so
no network/creds are needed; verifies the invite returns the Supabase UUID and
that a malformed response raises."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core import supabase_admin as sa


def _fake_client(user_id):
    admin = MagicMock()
    admin.invite_user_by_email.return_value = SimpleNamespace(
        user=SimpleNamespace(id=user_id)
    )
    return SimpleNamespace(auth=SimpleNamespace(admin=admin))


@pytest.mark.asyncio
async def test_invite_returns_uuid(monkeypatch):
    uid = uuid.uuid4()
    monkeypatch.setattr(sa, "_client", _fake_client(str(uid)))
    got = await sa.invite_user_by_email("x@example.com", redirect_to="http://app")
    assert got == uid


@pytest.mark.asyncio
async def test_invite_no_user_raises(monkeypatch):
    admin = MagicMock()
    admin.invite_user_by_email.return_value = SimpleNamespace(user=None)
    monkeypatch.setattr(sa, "_client", SimpleNamespace(auth=SimpleNamespace(admin=admin)))
    with pytest.raises(sa.SupabaseAdminError):
        await sa.invite_user_by_email("x@example.com")


@pytest.mark.asyncio
async def test_gotrue_error_normalized(monkeypatch):
    # The sync SDK raises gotrue's own AuthApiError (e.g. invalid email); we must
    # normalize it to SupabaseAdminError so the endpoint returns 502, not 500.
    from gotrue.errors import AuthApiError

    admin = MagicMock()
    admin.invite_user_by_email.side_effect = AuthApiError(
        "Email address is invalid", 400, "email_address_invalid"
    )
    monkeypatch.setattr(sa, "_client", SimpleNamespace(auth=SimpleNamespace(admin=admin)))
    with pytest.raises(sa.SupabaseAdminError, match="invalid"):
        await sa.invite_user_by_email("bad@example.com")
