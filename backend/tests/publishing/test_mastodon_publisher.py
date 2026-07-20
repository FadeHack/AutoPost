"""Mastodon publisher + OAuth unit tests.

Raw-httpx surface, so we inject `httpx.MockTransport` (same approach as the
LinkedIn client tests) — no network, no DB, no real instance.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.models.base import Platform
from app.publishing import mastodon as mast
from app.publishing import mastodon_oauth as mo
from app.publishing.base import (
    AuthPublishError,
    PermanentPublishError,
    PublishError,
    TransientPublishError,
)


def _patch_transport(monkeypatch, module, handler):
    """Force every `httpx.AsyncClient(...)` created in `module` to route through
    a MockTransport bound to `handler`."""
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)


def _account():
    return SimpleNamespace(
        instance_url="https://mastodon.social",
        access_token="encrypted",
    )


# ===========================================================================
# OAuth helper: normalize_instance
# ===========================================================================


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("mastodon.social", "https://mastodon.social"),
        ("https://mastodon.social/", "https://mastodon.social"),
        ("HACHYDERM.io", "https://hachyderm.io"),
        ("https://fosstodon.org/about", "https://fosstodon.org"),
    ],
)
def test_normalize_instance_ok(raw, expected):
    assert mo.normalize_instance(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "notahost", "has space"])
def test_normalize_instance_rejects_garbage(raw):
    with pytest.raises(mo.MastodonOAuthError):
        mo.normalize_instance(raw)


# ===========================================================================
# OAuth helper: state round-trip
# ===========================================================================


def test_state_round_trip(monkeypatch):
    monkeypatch.setattr(mo, "encrypt", lambda s: f"ENC[{s}]")
    monkeypatch.setattr(mo, "decrypt_with_ttl", lambda s, ttl: s[4:-1])

    state, nonce = mo.encode_state(
        "user-1", "https://mastodon.social", "cid", "csecret"
    )
    decoded = mo.decode_state(state)
    assert decoded.user_id == "user-1"
    assert decoded.instance == "https://mastodon.social"
    assert decoded.client_id == "cid"
    assert decoded.client_secret == "csecret"
    assert decoded.nonce == nonce


def test_decode_state_tampered_raises(monkeypatch):
    def _boom(_s, _ttl):
        raise ValueError("bad token")

    monkeypatch.setattr(mo, "decrypt_with_ttl", _boom)
    with pytest.raises(mo.MastodonOAuthError):
        mo.decode_state("whatever")


# ===========================================================================
# OAuth helper: register_app / exchange_code / verify_credentials
# ===========================================================================


async def test_register_app_happy(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/apps"
        return httpx.Response(
            200, json={"client_id": "CID", "client_secret": "CSECRET"}
        )

    _patch_transport(monkeypatch, mo, handler)
    app = await mo.register_app("https://mastodon.social")
    assert app.client_id == "CID"
    assert app.client_secret == "CSECRET"


async def test_register_app_non_200_raises(monkeypatch):
    _patch_transport(
        monkeypatch, mo, lambda r: httpx.Response(500, text="boom")
    )
    with pytest.raises(mo.MastodonOAuthError):
        await mo.register_app("https://mastodon.social")


async def test_exchange_code_happy(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/token"
        return httpx.Response(200, json={"access_token": "TOKEN123"})

    _patch_transport(monkeypatch, mo, handler)
    tok = await mo.exchange_code("https://mastodon.social", "cid", "cs", "code")
    assert tok == "TOKEN123"


async def test_exchange_code_no_token_raises(monkeypatch):
    _patch_transport(monkeypatch, mo, lambda r: httpx.Response(200, json={}))
    with pytest.raises(mo.MastodonOAuthError):
        await mo.exchange_code("https://mastodon.social", "cid", "cs", "code")


async def test_verify_credentials_happy(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/accounts/verify_credentials"
        assert request.headers["Authorization"] == "Bearer TOK"
        return httpx.Response(
            200,
            json={
                "id": "42",
                "username": "nestwhirr",
                "acct": "nestwhirr",
                "display_name": "Nestwhirr",
            },
        )

    _patch_transport(monkeypatch, mo, handler)
    profile = await mo.verify_credentials("https://mastodon.social", "TOK")
    assert profile.account_id == "42"
    assert profile.username == "nestwhirr"
    assert profile.display_name == "Nestwhirr"


async def test_verify_credentials_incomplete_raises(monkeypatch):
    _patch_transport(
        monkeypatch, mo, lambda r: httpx.Response(200, json={"id": "1"})
    )
    with pytest.raises(mo.MastodonOAuthError):
        await mo.verify_credentials("https://mastodon.social", "TOK")


# ===========================================================================
# Publisher: metadata
# ===========================================================================


def test_mastodon_publisher_metadata():
    assert mast.MastodonPublisher.platform == Platform.mastodon
    assert mast.MastodonPublisher.char_limit == 500
    assert mast.MastodonPublisher.max_images == 4
    assert mast.MastodonPublisher.supports_documents is False


# ===========================================================================
# Publisher: publish paths
# ===========================================================================


@pytest.fixture
def patch_download(monkeypatch):
    monkeypatch.setattr(mast, "decrypt", lambda s: "TOKEN")
    monkeypatch.setattr(mast.storage, "public_url", lambda p: f"https://cdn/{p}")
    monkeypatch.setattr(mast, "_download_png", AsyncMock(return_value=b"PNG"))


def _asset():
    return SimpleNamespace(
        id=uuid4(), image_path="post/a.png", template_id=uuid4()
    )


async def test_publish_text_only(monkeypatch, patch_download):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/statuses":
            captured["payload"] = json.loads(request.content)
            captured["auth"] = request.headers["Authorization"]
            return httpx.Response(
                200, json={"uri": "https://m/users/x/statuses/1"}
            )
        raise AssertionError(f"unexpected call {request.url.path}")

    _patch_transport(monkeypatch, mast, handler)
    result = await mast.MastodonPublisher().publish(
        session=None,
        post=SimpleNamespace(hook="Hook", body="b", tags=[]),
        account=_account(),
        commentary="Short post",
        assets=[],
    )
    assert result.external_urn == "https://m/users/x/statuses/1"
    assert captured["payload"]["status"] == "Short post"
    assert "media_ids" not in captured["payload"]
    assert captured["auth"] == "Bearer TOKEN"


async def test_publish_single_image_sync_media(monkeypatch, patch_download):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/media":
            return httpx.Response(200, json={"id": "M1", "url": "https://m/m1"})
        if request.url.path == "/api/v1/statuses":
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"uri": "https://m/s/2"})
        raise AssertionError(f"unexpected call {request.url.path}")

    _patch_transport(monkeypatch, mast, handler)
    result = await mast.MastodonPublisher().publish(
        session=None,
        post=SimpleNamespace(hook="A dog", body="b", tags=[]),
        account=_account(),
        commentary="caption",
        assets=[_asset()],
    )
    assert result.external_urn == "https://m/s/2"
    assert captured["payload"]["media_ids"] == ["M1"]


async def test_publish_media_async_then_poll(monkeypatch, patch_download):
    monkeypatch.setattr(mast.asyncio, "sleep", AsyncMock())
    calls = {"poll": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/media":
            # 202 = processing, no url yet.
            return httpx.Response(202, json={"id": "M9"})
        if request.url.path == "/api/v1/media/M9":
            calls["poll"] += 1
            if calls["poll"] < 2:
                return httpx.Response(206, json={"id": "M9", "url": None})
            return httpx.Response(200, json={"id": "M9", "url": "https://m/m9"})
        if request.url.path == "/api/v1/statuses":
            return httpx.Response(200, json={"uri": "https://m/s/3"})
        raise AssertionError(f"unexpected call {request.url.path}")

    _patch_transport(monkeypatch, mast, handler)
    result = await mast.MastodonPublisher().publish(
        session=None,
        post=SimpleNamespace(hook="h", body="b", tags=[]),
        account=_account(),
        commentary="caption",
        assets=[_asset()],
    )
    assert result.external_urn == "https://m/s/3"
    assert calls["poll"] >= 2


async def test_publish_truncates_carousel_to_4(monkeypatch, patch_download):
    uploaded = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/media":
            uploaded["count"] += 1
            return httpx.Response(
                200, json={"id": f"M{uploaded['count']}", "url": "https://m/x"}
            )
        if request.url.path == "/api/v1/statuses":
            payload = json.loads(request.content)
            uploaded["media_ids"] = payload["media_ids"]
            return httpx.Response(200, json={"uri": "https://m/s/4"})
        raise AssertionError(f"unexpected call {request.url.path}")

    _patch_transport(monkeypatch, mast, handler)
    await mast.MastodonPublisher().publish(
        session=None,
        post=SimpleNamespace(hook="h", body="b", tags=[]),
        account=_account(),
        commentary="caption",
        assets=[_asset() for _ in range(6)],
    )
    assert uploaded["count"] == 4
    assert len(uploaded["media_ids"]) == 4


@pytest.mark.parametrize(
    "status_code,exc",
    [
        (401, AuthPublishError),
        (403, AuthPublishError),
        (429, TransientPublishError),
        (503, TransientPublishError),
        (422, PermanentPublishError),
        (400, PermanentPublishError),
    ],
)
async def test_publish_classifies_status_errors(
    monkeypatch, patch_download, status_code, exc
):
    _patch_transport(
        monkeypatch,
        mast,
        lambda r: httpx.Response(status_code, text="err"),
    )
    with pytest.raises(exc):
        await mast.MastodonPublisher().publish(
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
    got = await mast.load_account(_Session(acc), post=SimpleNamespace(workspace_id=uuid4()))
    assert got is acc


async def test_load_account_raises_when_none():
    with pytest.raises(PermanentPublishError):
        await mast.load_account(_Session(None), post=SimpleNamespace(workspace_id=uuid4()))


# Sanity: every raised publish error is a PublishError subclass the orchestrator
# knows how to route.
def test_publish_errors_are_publisherror_subclasses():
    for e in (AuthPublishError, TransientPublishError, PermanentPublishError):
        assert issubclass(e, PublishError)
