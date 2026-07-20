"""Tenant-isolation (IDOR) guard for the posts API — Phase 14 Chunk C.

`_load_owned_post` is the single choke point every id-based post endpoint routes
through. It must return the post only when it belongs to the caller's workspace,
and raise 404 (never 403 — no existence leak) otherwise. Mock session, per the
repo's mock-first convention.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.posts import _load_owned_post
from app.models.post import Post


def _post(workspace_id: uuid.UUID) -> Post:
    return Post(id=uuid.uuid4(), workspace_id=workspace_id)


def _session(returns: Post | None) -> AsyncMock:
    s = AsyncMock()
    s.get = AsyncMock(return_value=returns)
    return s


@pytest.mark.asyncio
async def test_returns_post_when_workspace_matches():
    ws = uuid.uuid4()
    post = _post(ws)
    got = await _load_owned_post(_session(post), post.id, ws)
    assert got is post


@pytest.mark.asyncio
async def test_404_when_missing():
    with pytest.raises(HTTPException) as exc:
        await _load_owned_post(_session(None), uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_404_when_other_workspace():
    owner_ws = uuid.uuid4()
    attacker_ws = uuid.uuid4()
    post = _post(owner_ws)  # belongs to someone else
    with pytest.raises(HTTPException) as exc:
        await _load_owned_post(_session(post), post.id, attacker_ws)
    # 404, NOT 403 — attacker can't tell "not yours" from "doesn't exist".
    assert exc.value.status_code == 404
