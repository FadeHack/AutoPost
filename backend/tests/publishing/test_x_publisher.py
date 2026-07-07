"""X (Twitter) publisher + OAuth unit tests.

Raw-httpx surface, so we inject `httpx.MockTransport` (same approach as the
LinkedIn/Mastodon/Threads client tests) — no network, no DB, no real X app.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest

from app.models.base import Platform
from app.publishing import x as xp
from app.publishing import x_oauth as xo
from app.publishing.base import (
    AuthPublishError,
    PermanentPublishError,
    PublishError,
    TransientPublishError,
)


def _patch_transport(monkeypatch, module, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)


def _form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def _account(expires_in_hours: float = 2, refresh: str | None = "enc-refresh"):
    return SimpleNamespace(
        id=uuid4(),
        x_user_id="9001",
        username="nestwhirr",
        access_token="enc-access",
        refresh_token=refresh,
        expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=expires_in_hours),
    )


# ===========================================================================
# OAuth: PKCE + state round-trip
# ===========================================================================


def test_generate_pkce_is_s256():
    verifier, challenge = xo.generate_pkce()
    assert 43 <= len(verifier) <= 128
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == expected


def test_state_round_trip(monkeypatch):
    monkeypatch.setattr(xo, "encrypt", lambda s: f"ENC[{s}]")
    monkeypatch.setattr(xo, "decrypt_with_ttl", lambda s, ttl: s[4:-1])

    state, nonce = xo.encode_state("user-7", "VERIFIER123")
    decoded = xo.decode_state(state)
    assert decoded.user_id == "user-7"
    assert decoded.code_verifier == "VERIFIER123"
    assert decoded.nonce == nonce


def test_decode_state_tampered_raises(monkeypatch):
    def _boom(_s, _ttl):
        raise ValueError("bad token")

    monkeypatch.setattr(xo, "decrypt_with_ttl", _boom)
    with pytest.raises(xo.XOAuthError):
        xo.decode_state("whatever")


def test_build_authorize_url_has_pkce_params():
    url = xo.build_authorize_url("STATE123", "CHAL456")
    assert url.startswith("https://x.com/i/oauth2/authorize?")
    assert "response_type=code" in url
    assert "state=STATE123" in url
    assert "code_challenge=CHAL456" in url
    assert "code_challenge_method=S256" in url


# ===========================================================================
# OAuth: exchange_code / refresh / profile
# ===========================================================================


async def test_exchange_code_uses_basic_auth_and_returns_tokens(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/2/oauth2/token"
        captured["auth"] = request.headers.get("Authorization", "")
        captured["form"] = _form(request)
        return httpx.Response(
            200,
            json={
                "access_token": "ACCESS",
                "refresh_token": "REFRESH",
                "expires_in": 7200,
            },
        )

    _patch_transport(monkeypatch, xo, handler)
    tok = await xo.exchange_code("code", "verifier")
    assert tok.access_token == "ACCESS"
    assert tok.refresh_token == "REFRESH"
    assert tok.expires_at > datetime.now(tz=timezone.utc) + timedelta(hours=1)
    assert captured["auth"].startswith("Basic ")
    assert captured["form"]["grant_type"] == "authorization_code"
    assert captured["form"]["code_verifier"] == "verifier"


async def test_exchange_code_no_token_raises(monkeypatch):
    _patch_transport(monkeypatch, xo, lambda r: httpx.Response(200, json={}))
    with pytest.raises(xo.XOAuthError):
        await xo.exchange_code("code", "verifier")


async def test_refresh_token_rotates(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert _form(request)["grant_type"] == "refresh_token"
        return httpx.Response(
            200,
            json={
                "access_token": "NEW_ACCESS",
                "refresh_token": "NEW_REFRESH",
                "expires_in": 7200,
            },
        )

    _patch_transport(monkeypatch, xo, handler)
    tok = await xo.refresh_token("OLD_REFRESH")
    assert tok.access_token == "NEW_ACCESS"
    assert tok.refresh_token == "NEW_REFRESH"


async def test_fetch_profile_happy(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/2/users/me"
        return httpx.Response(
            200,
            json={"data": {"id": "9001", "username": "nestwhirr", "name": "Nestwhirr"}},
        )

    _patch_transport(monkeypatch, xo, handler)
    p = await xo.fetch_profile("ACCESS")
    assert p.x_user_id == "9001"
    assert p.username == "nestwhirr"
    assert p.display_name == "Nestwhirr"


async def test_fetch_profile_incomplete_raises(monkeypatch):
    _patch_transport(
        monkeypatch, xo, lambda r: httpx.Response(200, json={"data": {"id": "1"}})
    )
    with pytest.raises(xo.XOAuthError):
        await xo.fetch_profile("ACCESS")


# ===========================================================================
# Publisher: metadata + token staleness
# ===========================================================================


def test_x_publisher_metadata():
    assert xp.XPublisher.platform == Platform.x
    assert xp.XPublisher.char_limit == 280
    assert xp.XPublisher.max_images == 4
    assert xp.XPublisher.supports_documents is False


def test_is_token_stale():
    now = datetime.now(tz=timezone.utc)
    assert xp._is_token_stale(None) is False
    assert xp._is_token_stale(now + timedelta(hours=1)) is False
    assert xp._is_token_stale(now + timedelta(minutes=2)) is True
    # naive datetime tolerated
    assert xp._is_token_stale((now + timedelta(minutes=2)).replace(tzinfo=None)) is True


async def test_ensure_fresh_token_skips_when_fresh(monkeypatch):
    monkeypatch.setattr(xp, "decrypt", lambda s: "PLAIN")
    refresh = AsyncMock()
    monkeypatch.setattr(xp.xo, "refresh_token", refresh)
    tok = await xp._ensure_fresh_token(session=None, account=_account(2))
    assert tok == "PLAIN"
    refresh.assert_not_called()


async def test_ensure_fresh_token_refreshes_and_rotates(monkeypatch):
    monkeypatch.setattr(xp, "decrypt", lambda s: f"DEC[{s}]")
    monkeypatch.setattr(xp, "encrypt", lambda s: f"ENC[{s}]")
    monkeypatch.setattr(
        xp.xo,
        "refresh_token",
        AsyncMock(
            return_value=xo.XToken(
                access_token="NEW_A",
                refresh_token="NEW_R",
                expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=2),
            )
        ),
    )
    acct = _account(expires_in_hours=0)  # already at expiry → stale
    session = SimpleNamespace(flush=AsyncMock())
    tok = await xp._ensure_fresh_token(session=session, account=acct)
    assert tok == "NEW_A"
    assert acct.access_token == "ENC[NEW_A]"
    assert acct.refresh_token == "ENC[NEW_R]"
    session.flush.assert_awaited()


async def test_ensure_fresh_token_no_refresh_token_returns_stale(monkeypatch):
    monkeypatch.setattr(xp, "decrypt", lambda s: "PLAIN")
    refresh = AsyncMock()
    monkeypatch.setattr(xp.xo, "refresh_token", refresh)
    acct = _account(expires_in_hours=0, refresh=None)
    tok = await xp._ensure_fresh_token(session=None, account=acct)
    assert tok == "PLAIN"
    refresh.assert_not_called()


# ===========================================================================
# Publisher: publish paths
# ===========================================================================


@pytest.fixture
def patch_publish(monkeypatch):
    monkeypatch.setattr(xp, "decrypt", lambda s: "TOKEN")
    monkeypatch.setattr(xp.storage, "public_url", lambda p: f"https://cdn/{p}")


def _asset(path="post/a.png"):
    return SimpleNamespace(id=uuid4(), image_path=path, template_id=uuid4())


async def test_publish_text_only(monkeypatch, patch_publish):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/2/tweets":
            captured["body"] = json.loads(request.content.decode())
            return httpx.Response(201, json={"data": {"id": "TWEET1"}})
        raise AssertionError(f"unexpected call {request.url.path}")

    _patch_transport(monkeypatch, xp, handler)
    result = await xp.XPublisher().publish(
        session=None,
        post=SimpleNamespace(hook="h", body="b", tags=[]),
        account=_account(),
        commentary="Short post",
        assets=[],
    )
    assert result.external_urn == "TWEET1"
    assert captured["body"]["text"] == "Short post"
    assert "media" not in captured["body"]


async def test_publish_single_image_uploads_then_posts(monkeypatch, patch_publish):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/2/media/upload":
            return httpx.Response(200, json={"data": {"id": "MEDIA9"}})
        if path == "/2/tweets":
            captured["body"] = json.loads(request.content.decode())
            return httpx.Response(201, json={"data": {"id": "TWEET2"}})
        # asset download (cdn GET)
        return httpx.Response(200, content=b"\x89PNG")

    _patch_transport(monkeypatch, xp, handler)
    result = await xp.XPublisher().publish(
        session=None,
        post=SimpleNamespace(hook="h", body="b", tags=[]),
        account=_account(),
        commentary="caption",
        assets=[_asset()],
    )
    assert result.external_urn == "TWEET2"
    assert captured["body"]["media"]["media_ids"] == ["MEDIA9"]


async def test_publish_truncates_to_max_images(monkeypatch, patch_publish):
    uploads = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/2/media/upload":
            uploads["n"] += 1
            return httpx.Response(200, json={"data": {"id": f"M{uploads['n']}"}})
        if path == "/2/tweets":
            return httpx.Response(201, json={"data": {"id": "T"}})
        return httpx.Response(200, content=b"bytes")

    _patch_transport(monkeypatch, xp, handler)
    await xp.XPublisher().publish(
        session=None,
        post=SimpleNamespace(hook="h", body="b", tags=[]),
        account=_account(),
        commentary="caption",
        assets=[_asset() for _ in range(6)],
    )
    assert uploads["n"] == 4  # capped at X_MAX_IMAGES


async def test_publish_missing_tweet_id_raises(monkeypatch, patch_publish):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"data": {}})

    _patch_transport(monkeypatch, xp, handler)
    with pytest.raises(PermanentPublishError):
        await xp.XPublisher().publish(
            session=None,
            post=SimpleNamespace(hook="h", body="b", tags=[]),
            account=_account(),
            commentary="x",
            assets=[],
        )


@pytest.mark.parametrize(
    "status_code,exc",
    [
        (401, AuthPublishError),
        (429, TransientPublishError),
        (503, TransientPublishError),
        (403, PermanentPublishError),  # e.g. duplicate content / permission
        (400, PermanentPublishError),
    ],
)
async def test_publish_classifies_errors(monkeypatch, patch_publish, status_code, exc):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="err")

    _patch_transport(monkeypatch, xp, handler)
    with pytest.raises(exc):
        await xp.XPublisher().publish(
            session=None,
            post=SimpleNamespace(hook="h", body="b", tags=[]),
            account=_account(),
            commentary="x",
            assets=[],
        )


def test_content_type_for():
    assert xp._content_type_for("a/b.jpg") == "image/jpeg"
    assert xp._content_type_for("a/b.JPEG") == "image/jpeg"
    assert xp._content_type_for("a/b.png") == "image/png"


# ===========================================================================
# Account loader
# ===========================================================================


class _Result:
    def __init__(self, val):
        self._val = val

    def scalars(self):
        return self

    def first(self):
        return self._val


class _Session:
    def __init__(self, val):
        self._val = val

    async def execute(self, _stmt):
        return _Result(self._val)


async def test_load_account_returns_latest():
    acc = _account()
    assert await xp.load_account(_Session(acc), post=None) is acc


async def test_load_account_raises_when_none():
    with pytest.raises(PermanentPublishError):
        await xp.load_account(_Session(None), post=None)


def test_publish_errors_are_publisherror_subclasses():
    for e in (AuthPublishError, TransientPublishError, PermanentPublishError):
        assert issubclass(e, PublishError)
