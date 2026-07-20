"""Threads publisher + OAuth unit tests.

Raw-httpx surface, so we inject `httpx.MockTransport` (same approach as the
LinkedIn/Mastodon client tests) — no network, no DB, no real Meta app.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest

from app.models.base import Platform
from app.publishing import threads as th
from app.publishing import threads_oauth as to
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


def _account(expires_in_days: float = 60):
    return SimpleNamespace(
        id=uuid4(),
        threads_user_id="9001",
        access_token="encrypted",
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=expires_in_days),
    )


# ===========================================================================
# OAuth: state round-trip
# ===========================================================================


def test_state_round_trip(monkeypatch):
    monkeypatch.setattr(to, "encrypt", lambda s: f"ENC[{s}]")
    monkeypatch.setattr(to, "decrypt_with_ttl", lambda s, ttl: s[4:-1])

    state, nonce = to.encode_state("user-7")
    decoded = to.decode_state(state)
    assert decoded.user_id == "user-7"
    assert decoded.nonce == nonce


def test_decode_state_tampered_raises(monkeypatch):
    def _boom(_s, _ttl):
        raise ValueError("bad token")

    monkeypatch.setattr(to, "decrypt_with_ttl", _boom)
    with pytest.raises(to.ThreadsOAuthError):
        to.decode_state("whatever")


def test_build_authorize_url_has_params():
    url = to.build_authorize_url("STATE123")
    assert url.startswith("https://threads.net/oauth/authorize?")
    assert "response_type=code" in url
    assert "state=STATE123" in url
    assert "scope=" in url


# ===========================================================================
# OAuth: exchange_code / exchange_long_lived / refresh / profile
# ===========================================================================


async def test_exchange_code_happy(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/access_token"
        return httpx.Response(200, json={"access_token": "SHORT", "user_id": "9001"})

    _patch_transport(monkeypatch, to, handler)
    assert await to.exchange_code("code") == "SHORT"


async def test_exchange_code_no_token_raises(monkeypatch):
    _patch_transport(monkeypatch, to, lambda r: httpx.Response(200, json={}))
    with pytest.raises(to.ThreadsOAuthError):
        await to.exchange_code("code")


async def test_exchange_long_lived_happy(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/access_token"
        assert request.url.params["grant_type"] == "th_exchange_token"
        return httpx.Response(
            200, json={"access_token": "LONG", "expires_in": 5184000}
        )

    _patch_transport(monkeypatch, to, handler)
    tok = await to.exchange_long_lived("SHORT")
    assert tok.access_token == "LONG"
    # ~60 days out
    assert tok.expires_at > datetime.now(tz=timezone.utc) + timedelta(days=59)


async def test_refresh_long_lived_happy(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/refresh_access_token"
        assert request.url.params["grant_type"] == "th_refresh_token"
        return httpx.Response(
            200, json={"access_token": "FRESH", "expires_in": 5184000}
        )

    _patch_transport(monkeypatch, to, handler)
    tok = await to.refresh_long_lived("LONG")
    assert tok.access_token == "FRESH"


async def test_fetch_profile_happy(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/me")
        return httpx.Response(
            200, json={"id": "9001", "username": "nestwhirr", "name": "Nestwhirr"}
        )

    _patch_transport(monkeypatch, to, handler)
    p = await to.fetch_profile("LONG")
    assert p.threads_user_id == "9001"
    assert p.username == "nestwhirr"
    assert p.display_name == "Nestwhirr"


async def test_fetch_profile_incomplete_raises(monkeypatch):
    _patch_transport(monkeypatch, to, lambda r: httpx.Response(200, json={"id": "1"}))
    with pytest.raises(to.ThreadsOAuthError):
        await to.fetch_profile("LONG")


# ===========================================================================
# Publisher: metadata + token staleness
# ===========================================================================


def test_threads_publisher_metadata():
    assert th.ThreadsPublisher.platform == Platform.threads
    assert th.ThreadsPublisher.char_limit == 500
    assert th.ThreadsPublisher.max_images == 20
    assert th.ThreadsPublisher.supports_documents is False


def test_is_token_stale():
    now = datetime.now(tz=timezone.utc)
    assert th._is_token_stale(None) is False
    assert th._is_token_stale(now + timedelta(days=30)) is False
    assert th._is_token_stale(now + timedelta(hours=1)) is True
    # naive datetime tolerated
    assert th._is_token_stale((now + timedelta(hours=1)).replace(tzinfo=None)) is True


async def test_ensure_fresh_token_skips_when_fresh(monkeypatch):
    monkeypatch.setattr(th, "decrypt", lambda s: "PLAIN")
    refresh = AsyncMock()
    monkeypatch.setattr(th.to, "refresh_long_lived", refresh)
    tok = await th._ensure_fresh_token(session=None, account=_account(60))
    assert tok == "PLAIN"
    refresh.assert_not_called()


async def test_ensure_fresh_token_refreshes_when_stale(monkeypatch):
    monkeypatch.setattr(th, "decrypt", lambda s: "PLAIN")
    monkeypatch.setattr(th, "encrypt", lambda s: f"ENC[{s}]")
    monkeypatch.setattr(
        th.to,
        "refresh_long_lived",
        AsyncMock(
            return_value=to.LongLivedToken(
                access_token="NEW",
                expires_at=datetime.now(tz=timezone.utc) + timedelta(days=60),
            )
        ),
    )
    acct = _account(expires_in_days=0.5)  # within the 2-day lead
    session = SimpleNamespace(flush=AsyncMock())
    tok = await th._ensure_fresh_token(session=session, account=acct)
    assert tok == "NEW"
    assert acct.access_token == "ENC[NEW]"
    session.flush.assert_awaited()


# ===========================================================================
# Publisher: publish paths
# ===========================================================================


@pytest.fixture
def patch_publish(monkeypatch):
    monkeypatch.setattr(th, "decrypt", lambda s: "TOKEN")
    monkeypatch.setattr(th.storage, "public_url", lambda p: f"https://cdn/{p}")
    monkeypatch.setattr(th.asyncio, "sleep", AsyncMock())


def _asset():
    return SimpleNamespace(id=uuid4(), image_path="post/a.png", template_id=uuid4())


async def test_publish_text_only(monkeypatch, patch_publish):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/threads_publish"):
            captured["publish"] = _form(request)
            return httpx.Response(200, json={"id": "MEDIA1"})
        if path.endswith("/threads"):
            captured["container"] = _form(request)
            return httpx.Response(200, json={"id": "C1"})
        # status poll
        return httpx.Response(200, json={"status": "FINISHED"})

    _patch_transport(monkeypatch, th, handler)
    result = await th.ThreadsPublisher().publish(
        session=None,
        post=SimpleNamespace(hook="h", body="b", tags=[]),
        account=_account(),
        commentary="Short post",
        assets=[],
    )
    assert result.external_urn == "MEDIA1"
    assert captured["container"]["media_type"] == "TEXT"
    assert captured["container"]["text"] == "Short post"
    assert captured["publish"]["creation_id"] == "C1"


async def test_publish_single_image(monkeypatch, patch_publish):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/threads_publish"):
            return httpx.Response(200, json={"id": "MEDIA2"})
        if path.endswith("/threads"):
            captured["container"] = _form(request)
            return httpx.Response(200, json={"id": "C2"})
        return httpx.Response(200, json={"status": "FINISHED"})

    _patch_transport(monkeypatch, th, handler)
    result = await th.ThreadsPublisher().publish(
        session=None,
        post=SimpleNamespace(hook="h", body="b", tags=[]),
        account=_account(),
        commentary="caption",
        assets=[_asset()],
    )
    assert result.external_urn == "MEDIA2"
    assert captured["container"]["media_type"] == "IMAGE"
    assert captured["container"]["image_url"].startswith("https://cdn/")


async def test_publish_carousel(monkeypatch, patch_publish):
    state = {"items": 0, "carousel_children": None}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/threads_publish"):
            return httpx.Response(200, json={"id": "MEDIA3"})
        if path.endswith("/threads"):
            form = _form(request)
            if form.get("is_carousel_item") == "true":
                state["items"] += 1
                return httpx.Response(200, json={"id": f"ITEM{state['items']}"})
            # parent CAROUSEL container
            state["carousel_children"] = form["children"]
            assert form["media_type"] == "CAROUSEL"
            return httpx.Response(200, json={"id": "CAR"})
        return httpx.Response(200, json={"status": "FINISHED"})

    _patch_transport(monkeypatch, th, handler)
    result = await th.ThreadsPublisher().publish(
        session=None,
        post=SimpleNamespace(hook="h", body="b", tags=[]),
        account=_account(),
        commentary="caption",
        assets=[_asset(), _asset(), _asset()],
    )
    assert result.external_urn == "MEDIA3"
    assert state["items"] == 3
    assert state["carousel_children"] == "ITEM1,ITEM2,ITEM3"


async def test_publish_truncates_to_max_images(monkeypatch, patch_publish):
    monkeypatch.setattr(th, "THREADS_MAX_IMAGES", 4)
    state = {"items": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/threads_publish"):
            return httpx.Response(200, json={"id": "M"})
        if path.endswith("/threads"):
            form = _form(request)
            if form.get("is_carousel_item") == "true":
                state["items"] += 1
                return httpx.Response(200, json={"id": f"I{state['items']}"})
            return httpx.Response(200, json={"id": "CAR"})
        return httpx.Response(200, json={"status": "FINISHED"})

    _patch_transport(monkeypatch, th, handler)
    await th.ThreadsPublisher().publish(
        session=None,
        post=SimpleNamespace(hook="h", body="b", tags=[]),
        account=_account(),
        commentary="caption",
        assets=[_asset() for _ in range(6)],
    )
    assert state["items"] == 4


async def test_publish_container_error_status_permanent(monkeypatch, patch_publish):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/threads"):
            return httpx.Response(200, json={"id": "C"})
        # status poll returns ERROR
        return httpx.Response(
            200, json={"status": "ERROR", "error_message": "bad media"}
        )

    _patch_transport(monkeypatch, th, handler)
    with pytest.raises(PermanentPublishError):
        await th.ThreadsPublisher().publish(
            session=None,
            post=SimpleNamespace(hook="h", body="b", tags=[]),
            account=_account(),
            commentary="caption",
            assets=[_asset()],
        )


@pytest.mark.parametrize(
    "status_code,body,exc",
    [
        (401, "err", AuthPublishError),
        (403, "err", AuthPublishError),
        (429, "err", TransientPublishError),
        (503, "err", TransientPublishError),
        (422, "err", PermanentPublishError),
        (400, "err", PermanentPublishError),
        # Meta returns 400 with an OAuthException for a dead token → Auth.
        (400, '{"error":{"type":"OAuthException","code":190}}', AuthPublishError),
    ],
)
async def test_publish_classifies_errors(
    monkeypatch, patch_publish, status_code, body, exc
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=body)

    _patch_transport(monkeypatch, th, handler)
    with pytest.raises(exc):
        await th.ThreadsPublisher().publish(
            session=None,
            post=SimpleNamespace(hook="h", body="b", tags=[]),
            account=_account(),
            commentary="x",
            assets=[],
        )


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
    assert await th.load_account(_Session(acc), post=SimpleNamespace(workspace_id=uuid4())) is acc


async def test_load_account_raises_when_none():
    with pytest.raises(PermanentPublishError):
        await th.load_account(_Session(None), post=SimpleNamespace(workspace_id=uuid4()))


def test_publish_errors_are_publisherror_subclasses():
    for e in (AuthPublishError, TransientPublishError, PermanentPublishError):
        assert issubclass(e, PublishError)
