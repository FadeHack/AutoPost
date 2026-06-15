"""BlueskyPublisher unit tests.

We monkey-patch the atproto `Client` symbol so the SDK's `login` /
`send_post` / `send_images` paths are exercised without hitting the network.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.models.base import Platform
from app.publishing import bluesky as bsky
from app.publishing.base import (
    PermanentPublishError,
    TransientPublishError,
)


class _FakeClient:
    """In-process stand-in for atproto.Client. Captures the calls each
    test wants to assert on."""

    calls: dict[str, object] = {}

    def __init__(self):
        type(self).calls.clear()

    def login(self, handle, password):
        type(self).calls["login"] = (handle, password)

    def send_post(self, text):
        type(self).calls["send_post"] = text
        return SimpleNamespace(
            uri="at://did:plc:abc/app.bsky.feed.post/xyz"
        )

    def send_images(self, text, images, image_alts):
        type(self).calls["send_images"] = {
            "text": text,
            "images": images,
            "image_alts": image_alts,
        }
        return SimpleNamespace(
            uri="at://did:plc:abc/app.bsky.feed.post/img"
        )


def _account():
    return SimpleNamespace(
        handle="nestwhirr.bsky.social",
        app_password="encrypted",
    )


@pytest.fixture
def patched(monkeypatch):
    """Stub decrypt + asset download + atproto.Client import."""
    monkeypatch.setattr(bsky, "decrypt", lambda s: "plaintext-pwd")
    monkeypatch.setattr(bsky.storage, "public_url", lambda p: f"https://cdn/{p}")
    monkeypatch.setattr(
        bsky, "_download_png", _async_returning(b"PNG")
    )

    # Patch the import inside publish() by inserting a fake module.
    import sys
    fake_module = MagicMock()
    fake_module.Client = _FakeClient
    sys.modules["atproto"] = fake_module
    return _FakeClient


def _async_returning(value):
    async def _f(*_args, **_kwargs):
        return value
    return _f


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_bluesky_publish_text_only(patched):
    publisher = bsky.BlueskyPublisher()
    post = SimpleNamespace(hook="Hook.", body="Body.", tags=[])
    account = _account()

    result = await publisher.publish(
        session=None,
        post=post,
        account=account,
        commentary="Short post",
        assets=[],
    )

    assert result.external_urn.startswith("at://")
    assert _FakeClient.calls["login"] == ("nestwhirr.bsky.social", "plaintext-pwd")
    assert _FakeClient.calls["send_post"] == "Short post"
    # No image path engaged on text-only.
    assert "send_images" not in _FakeClient.calls


async def test_bluesky_publish_single_image(patched):
    publisher = bsky.BlueskyPublisher()
    asset = SimpleNamespace(
        id=uuid4(), image_path="post/a.png", linkedin_asset_urn=None, template_id=uuid4()
    )
    post = SimpleNamespace(hook="A photo of my dog", body="b", tags=[])
    account = _account()

    result = await publisher.publish(
        session=None,
        post=post,
        account=account,
        commentary="caption",
        assets=[asset],
    )

    assert result.external_urn.endswith("/img")
    sent = _FakeClient.calls["send_images"]
    assert sent["text"] == "caption"
    assert sent["images"] == [b"PNG"]
    # Hook used as alt text.
    assert sent["image_alts"] == ["A photo of my dog"]


async def test_bluesky_publish_truncates_carousel_to_4_images(patched):
    """Bluesky caps at 4 images. Anything beyond is silently dropped
    (operator pre-warned at approve time via `max_images=4`)."""
    publisher = bsky.BlueskyPublisher()
    assets = [
        SimpleNamespace(
            id=uuid4(), image_path=f"post/a{i}.png",
            linkedin_asset_urn=None, template_id=uuid4()
        )
        for i in range(6)
    ]
    post = SimpleNamespace(hook="Hook", body="b", tags=[])
    account = _account()

    await publisher.publish(
        session=None,
        post=post,
        account=account,
        commentary="caption",
        assets=assets,
    )

    sent = _FakeClient.calls["send_images"]
    assert len(sent["images"]) == 4


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


async def test_bluesky_publish_invalid_password_is_permanent(patched, monkeypatch):
    class _AuthFailClient(_FakeClient):
        def login(self, handle, password):
            raise RuntimeError("Invalid identifier or password")

    import sys
    sys.modules["atproto"].Client = _AuthFailClient

    publisher = bsky.BlueskyPublisher()
    post = SimpleNamespace(hook="h", body="b", tags=[])
    account = _account()

    with pytest.raises(PermanentPublishError, match="auth"):
        await publisher.publish(
            session=None,
            post=post,
            account=account,
            commentary="x",
            assets=[],
        )


async def test_bluesky_publish_rate_limit_is_transient(patched):
    class _RateClient(_FakeClient):
        def send_post(self, text):
            raise RuntimeError("Rate limit exceeded (429)")

    import sys
    sys.modules["atproto"].Client = _RateClient

    publisher = bsky.BlueskyPublisher()
    post = SimpleNamespace(hook="h", body="b", tags=[])
    account = _account()

    with pytest.raises(TransientPublishError, match="transient"):
        await publisher.publish(
            session=None,
            post=post,
            account=account,
            commentary="x",
            assets=[],
        )


async def test_bluesky_publish_unknown_error_defaults_to_transient(patched):
    """Unknown errors default to transient — safer to retry than swallow an
    outage as permanent."""
    class _BoomClient(_FakeClient):
        def send_post(self, text):
            raise RuntimeError("???")

    import sys
    sys.modules["atproto"].Client = _BoomClient

    publisher = bsky.BlueskyPublisher()
    post = SimpleNamespace(hook="h", body="b", tags=[])
    account = _account()

    with pytest.raises(TransientPublishError):
        await publisher.publish(
            session=None,
            post=post,
            account=account,
            commentary="x",
            assets=[],
        )


# ---------------------------------------------------------------------------
# Class metadata (used by orchestrator to gate char limit + image cap)
# ---------------------------------------------------------------------------


def test_bluesky_publisher_metadata():
    assert bsky.BlueskyPublisher.platform == Platform.bluesky
    assert bsky.BlueskyPublisher.char_limit == 300
    assert bsky.BlueskyPublisher.max_images == 4
    assert bsky.BlueskyPublisher.supports_documents is False
