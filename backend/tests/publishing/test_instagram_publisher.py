"""Instagram publisher + OAuth unit tests.

Raw-httpx surface, so we inject `httpx.MockTransport` (same approach as the
LinkedIn/Mastodon/Threads client tests) — no network, no DB, no real Meta app.

Instagram deltas vs Threads exercised here:
  - no text-only post (empty assets → PermanentPublishError)
  - caption param (not `text`), container status field `status_code`
  - code exchange returns a short-lived token + IG user id (flat OR wrapped body)
  - carousel cap is 10 (not 20)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.models.base import Platform
from app.publishing import instagram as ig
from app.publishing import instagram_oauth as io
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


def _account(expires_in_days: float = 60):
    return SimpleNamespace(
        id=uuid4(),
        instagram_user_id="9001",
        access_token="encrypted",
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=expires_in_days),
    )


# ===========================================================================
# OAuth: state round-trip
# ===========================================================================


def test_state_round_trip(monkeypatch):
    monkeypatch.setattr(io, "encrypt", lambda s: f"ENC[{s}]")
    monkeypatch.setattr(io, "decrypt_with_ttl", lambda s, ttl: s[4:-1])

    state, nonce = io.encode_state("user-7")
    decoded = io.decode_state(state)
    assert decoded.user_id == "user-7"
    assert decoded.nonce == nonce


def test_decode_state_tampered_raises(monkeypatch):
    def _boom(_s, _ttl):
        raise ValueError("bad token")

    monkeypatch.setattr(io, "decrypt_with_ttl", _boom)
    with pytest.raises(io.InstagramOAuthError):
        io.decode_state("whatever")


def test_build_authorize_url_has_params():
    url = io.build_authorize_url("STATE123")
    assert url.startswith("https://www.instagram.com/oauth/authorize?")
    assert "response_type=code" in url
    assert "state=STATE123" in url
    assert "scope=" in url


# ===========================================================================
# OAuth: exchange_code (flat + wrapped) / long-lived / refresh / profile
# ===========================================================================


async def test_exchange_code_flat_body(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/access_token"
        return httpx.Response(200, json={"access_token": "SHORT", "user_id": 9001})

    _patch_transport(monkeypatch, io, handler)
    tok = await io.exchange_code("code")
    assert tok.access_token == "SHORT"
    assert tok.instagram_user_id == "9001"


async def test_exchange_code_wrapped_body(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"access_token": "SHORT", "user_id": "9001", "permissions": "x"}]},
        )

    _patch_transport(monkeypatch, io, handler)
    tok = await io.exchange_code("code")
    assert tok.access_token == "SHORT"
    assert tok.instagram_user_id == "9001"


async def test_exchange_code_missing_fields_raises(monkeypatch):
    _patch_transport(monkeypatch, io, lambda r: httpx.Response(200, json={"access_token": "x"}))
    with pytest.raises(io.InstagramOAuthError):
        await io.exchange_code("code")


async def test_exchange_long_lived_happy(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/access_token"
        assert request.url.params["grant_type"] == "ig_exchange_token"
        return httpx.Response(200, json={"access_token": "LONG", "expires_in": 5184000})

    _patch_transport(monkeypatch, io, handler)
    tok = await io.exchange_long_lived("SHORT")
    assert tok.access_token == "LONG"
    assert tok.expires_at > datetime.now(tz=timezone.utc) + timedelta(days=59)


async def test_refresh_long_lived_happy(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/refresh_access_token"
        assert request.url.params["grant_type"] == "ig_refresh_token"
        return httpx.Response(200, json={"access_token": "FRESH", "expires_in": 5184000})

    _patch_transport(monkeypatch, io, handler)
    tok = await io.refresh_long_lived("LONG")
    assert tok.access_token == "FRESH"


async def test_fetch_profile_happy(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/me")
        return httpx.Response(
            200,
            json={"user_id": "9001", "username": "nestwhirr", "account_type": "BUSINESS"},
        )

    _patch_transport(monkeypatch, io, handler)
    p = await io.fetch_profile("LONG")
    assert p.instagram_user_id == "9001"
    assert p.username == "nestwhirr"
    assert p.account_type == "BUSINESS"


async def test_fetch_profile_accepts_legacy_id_field(monkeypatch):
    # Older Graph responses ship `id` instead of `user_id`.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "42", "username": "nest"})

    _patch_transport(monkeypatch, io, handler)
    p = await io.fetch_profile("LONG")
    assert p.instagram_user_id == "42"


async def test_fetch_profile_incomplete_raises(monkeypatch):
    _patch_transport(monkeypatch, io, lambda r: httpx.Response(200, json={"user_id": "1"}))
    with pytest.raises(io.InstagramOAuthError):
        await io.fetch_profile("LONG")


# ===========================================================================
# Publisher: metadata + token staleness
# ===========================================================================


def test_instagram_publisher_metadata():
    assert ig.InstagramPublisher.platform == Platform.instagram
    assert ig.InstagramPublisher.char_limit == 2200
    assert ig.InstagramPublisher.max_images == 10
    assert ig.InstagramPublisher.supports_documents is False


def test_is_token_stale():
    now = datetime.now(tz=timezone.utc)
    assert ig._is_token_stale(None) is False
    assert ig._is_token_stale(now + timedelta(days=30)) is False
    assert ig._is_token_stale(now + timedelta(hours=1)) is True
    assert ig._is_token_stale((now + timedelta(hours=1)).replace(tzinfo=None)) is True


async def test_ensure_fresh_token_skips_when_fresh(monkeypatch):
    monkeypatch.setattr(ig, "decrypt", lambda s: "PLAIN")
    refresh = AsyncMock()
    monkeypatch.setattr(ig.io, "refresh_long_lived", refresh)
    tok = await ig._ensure_fresh_token(session=None, account=_account(60))
    assert tok == "PLAIN"
    refresh.assert_not_called()


async def test_ensure_fresh_token_refreshes_when_stale(monkeypatch):
    monkeypatch.setattr(ig, "decrypt", lambda s: "PLAIN")
    monkeypatch.setattr(ig, "encrypt", lambda s: f"ENC[{s}]")
    monkeypatch.setattr(
        ig.io,
        "refresh_long_lived",
        AsyncMock(
            return_value=io.LongLivedToken(
                access_token="NEW",
                expires_at=datetime.now(tz=timezone.utc) + timedelta(days=60),
            )
        ),
    )
    acct = _account(expires_in_days=0.5)
    session = SimpleNamespace(flush=AsyncMock())
    tok = await ig._ensure_fresh_token(session=session, account=acct)
    assert tok == "NEW"
    assert acct.access_token == "ENC[NEW]"
    session.flush.assert_awaited()


# ===========================================================================
# Publisher: publish paths
# ===========================================================================


@pytest.fixture
def patch_publish(monkeypatch):
    monkeypatch.setattr(ig, "decrypt", lambda s: "TOKEN")
    monkeypatch.setattr(ig.storage, "public_url", lambda p: f"https://cdn/{p}")
    monkeypatch.setattr(ig.asyncio, "sleep", AsyncMock())


def _asset():
    return SimpleNamespace(id=uuid4(), image_path="post/a.png", template_id=uuid4())


async def test_publish_requires_image(monkeypatch, patch_publish):
    # Instagram has no text-only post — empty assets must fail permanently.
    with pytest.raises(PermanentPublishError):
        await ig.InstagramPublisher().publish(
            session=None,
            post=SimpleNamespace(hook="h", body="b", tags=[]),
            account=_account(),
            commentary="caption",
            assets=[],
        )


async def test_publish_single_image(monkeypatch, patch_publish):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/media_publish"):
            captured["publish"] = dict(httpx.QueryParams(request.content.decode()))
            return httpx.Response(200, json={"id": "MEDIA2"})
        if path.endswith("/media"):
            captured["container"] = dict(httpx.QueryParams(request.content.decode()))
            return httpx.Response(200, json={"id": "C2"})
        return httpx.Response(200, json={"status_code": "FINISHED"})

    _patch_transport(monkeypatch, ig, handler)
    result = await ig.InstagramPublisher().publish(
        session=None,
        post=SimpleNamespace(hook="h", body="b", tags=[]),
        account=_account(),
        commentary="caption",
        assets=[_asset()],
    )
    assert result.external_urn == "MEDIA2"
    assert captured["container"]["caption"] == "caption"
    assert captured["container"]["image_url"].startswith("https://cdn/")
    assert "media_type" not in captured["container"]
    assert captured["publish"]["creation_id"] == "C2"


async def test_publish_carousel(monkeypatch, patch_publish):
    state = {"items": 0, "carousel_children": None}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "MEDIA3"})
        if path.endswith("/media"):
            form = dict(httpx.QueryParams(request.content.decode()))
            if form.get("is_carousel_item") == "true":
                state["items"] += 1
                return httpx.Response(200, json={"id": f"ITEM{state['items']}"})
            state["carousel_children"] = form["children"]
            assert form["media_type"] == "CAROUSEL"
            return httpx.Response(200, json={"id": "CAR"})
        return httpx.Response(200, json={"status_code": "FINISHED"})

    _patch_transport(monkeypatch, ig, handler)
    result = await ig.InstagramPublisher().publish(
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
    monkeypatch.setattr(ig, "INSTAGRAM_MAX_IMAGES", 4)
    state = {"items": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "M"})
        if path.endswith("/media"):
            form = dict(httpx.QueryParams(request.content.decode()))
            if form.get("is_carousel_item") == "true":
                state["items"] += 1
                return httpx.Response(200, json={"id": f"I{state['items']}"})
            return httpx.Response(200, json={"id": "CAR"})
        return httpx.Response(200, json={"status_code": "FINISHED"})

    _patch_transport(monkeypatch, ig, handler)
    await ig.InstagramPublisher().publish(
        session=None,
        post=SimpleNamespace(hook="h", body="b", tags=[]),
        account=_account(),
        commentary="caption",
        assets=[_asset() for _ in range(6)],
    )
    assert state["items"] == 4


async def test_publish_container_error_status_permanent(monkeypatch, patch_publish):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "C"})
        return httpx.Response(200, json={"status_code": "ERROR", "status": "bad media"})

    _patch_transport(monkeypatch, ig, handler)
    with pytest.raises(PermanentPublishError):
        await ig.InstagramPublisher().publish(
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

    _patch_transport(monkeypatch, ig, handler)
    with pytest.raises(exc):
        await ig.InstagramPublisher().publish(
            session=None,
            post=SimpleNamespace(hook="h", body="b", tags=[]),
            account=_account(),
            commentary="x",
            assets=[_asset()],
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
    assert await ig.load_account(_Session(acc), post=SimpleNamespace(workspace_id=uuid4())) is acc


async def test_load_account_raises_when_none():
    with pytest.raises(PermanentPublishError):
        await ig.load_account(_Session(None), post=SimpleNamespace(workspace_id=uuid4()))


def test_publish_errors_are_publisherror_subclasses():
    for e in (AuthPublishError, TransientPublishError, PermanentPublishError):
        assert issubclass(e, PublishError)
