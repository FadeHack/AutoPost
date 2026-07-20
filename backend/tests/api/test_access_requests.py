"""Public access-request intake — Phase 14 Chunk E.

Covers the spam guards (honeypot, IP rate limit), email validation, dedupe, and
the happy path. Mock session per the repo's mock-first convention; the limiter
is exercised directly (it's pure in-memory).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.api.access_requests import (
    AccessRequestCreate,
    _limiter,
    create_access_request,
)
from app.core.ratelimit import InMemoryRateLimiter, client_ip


def _request(ip: str = "203.0.113.7") -> SimpleNamespace:
    return SimpleNamespace(
        headers={},
        client=SimpleNamespace(host=ip),
    )


def _session(existing: object | None = None) -> AsyncMock:
    """Mock async session. `execute(...).first()` returns `existing` (the dedupe
    lookup); add/commit are no-ops we can assert on."""
    s = AsyncMock()
    result = SimpleNamespace(first=lambda: existing)
    s.execute = AsyncMock(return_value=result)
    s.add = lambda obj: None
    s.commit = AsyncMock()
    return s


# --- validation ---------------------------------------------------------------


def test_email_validation_rejects_garbage():
    with pytest.raises(ValidationError):
        AccessRequestCreate(email="not-an-email")


def test_email_is_stripped():
    m = AccessRequestCreate(email="  a@b.co  ")
    assert m.email == "a@b.co"


# --- happy path ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_creates_pending_request(monkeypatch):
    # Fresh limiter so prior tests' counts don't bleed in.
    monkeypatch.setattr(
        "app.api.access_requests._limiter",
        InMemoryRateLimiter(limit=5, window_seconds=3600),
    )
    session = _session(existing=None)
    added: list = []
    session.add = added.append
    payload = AccessRequestCreate(email="Founder@Example.com", name="Ada")

    ack = await create_access_request(payload, _request(), session)

    assert ack.ok is True
    assert len(added) == 1
    assert added[0].email == "founder@example.com"  # lowercased
    session.commit.assert_awaited_once()


# --- spam guards --------------------------------------------------------------


@pytest.mark.asyncio
async def test_honeypot_drops_silently(monkeypatch):
    monkeypatch.setattr(
        "app.api.access_requests._limiter",
        InMemoryRateLimiter(limit=5, window_seconds=3600),
    )
    session = _session()
    payload = AccessRequestCreate(email="bot@spam.co", website="http://spam")

    ack = await create_access_request(payload, _request(), session)

    assert ack.ok is True  # opaque — looks successful
    session.commit.assert_not_awaited()  # nothing persisted


@pytest.mark.asyncio
async def test_dedupes_open_request(monkeypatch):
    monkeypatch.setattr(
        "app.api.access_requests._limiter",
        InMemoryRateLimiter(limit=5, window_seconds=3600),
    )
    session = _session(existing=("some-id",))  # a pending row already exists
    payload = AccessRequestCreate(email="dupe@example.com")

    ack = await create_access_request(payload, _request(), session)

    assert ack.ok is True
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_cap(monkeypatch):
    limiter = InMemoryRateLimiter(limit=3, window_seconds=3600)
    monkeypatch.setattr("app.api.access_requests._limiter", limiter)
    payload = AccessRequestCreate(email="flood@example.com")

    committed = 0
    for _ in range(5):
        session = _session(existing=None)
        await create_access_request(payload, _request("198.51.100.9"), session)
        committed += session.commit.await_count
    # Only the first 3 within the window persist; the rest are dropped.
    assert committed == 3


# --- limiter + ip helper units ------------------------------------------------


def test_limiter_is_per_key():
    limiter = InMemoryRateLimiter(limit=1, window_seconds=3600)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is True  # different key, own bucket


def test_client_ip_prefers_forwarded_header():
    req = SimpleNamespace(
        headers={"x-forwarded-for": "70.0.0.1, 10.0.0.1"},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    assert client_ip(req) == "70.0.0.1"


def test_client_ip_falls_back_to_peer():
    assert client_ip(_request("192.0.2.5")) == "192.0.2.5"
