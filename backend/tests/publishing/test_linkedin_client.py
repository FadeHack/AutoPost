"""Tests for the LinkedIn HTTP client.

No real network. Every test injects an httpx.MockTransport so we assert on the
exact request shape (URL, headers, body) and stub responses precisely.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.publishing import linkedin_client as lc


@pytest.fixture
def patch_httpx(monkeypatch):
    """Replace httpx.AsyncClient inside linkedin_client with one wired to a MockTransport."""

    def _apply(handler):
        real_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(lc.httpx, "AsyncClient", factory)

    return _apply


# --- escape_commentary ---


def test_escape_commentary_backslashes_reserved_chars():
    text = "Hello (world) #tag <ok> @user"
    out = lc.escape_commentary(text)
    for ch in "()#<>@":
        assert "\\" + ch in out
    # Plain alpha untouched
    assert "Hello" in out


def test_escape_commentary_leaves_plain_text_alone():
    assert lc.escape_commentary("just words and numbers 42") == "just words and numbers 42"


# --- author_urn ---


def test_author_urn_personal():
    assert lc.author_urn("personal", member_sub="abc123", org_urn=None) == "urn:li:person:abc123"


def test_author_urn_organization():
    assert (
        lc.author_urn("organization", member_sub=None, org_urn="98765")
        == "urn:li:organization:98765"
    )


def test_author_urn_personal_missing_sub_raises():
    with pytest.raises(ValueError, match="member_sub"):
        lc.author_urn("personal", member_sub=None, org_urn=None)


def test_author_urn_org_missing_urn_raises():
    with pytest.raises(ValueError, match="org_urn"):
        lc.author_urn("organization", member_sub="x", org_urn=None)


def test_author_urn_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown account_kind"):
        lc.author_urn("group", member_sub=None, org_urn=None)


# --- initialize_image_upload ---


async def test_initialize_image_upload_happy(patch_httpx):
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json={
                "value": {
                    "uploadUrl": "https://upload.linkedin.example/x",
                    "image": "urn:li:image:ABC123",
                    "uploadUrlExpiresAt": 1700000000000,
                }
            },
        )

    patch_httpx(handler)
    result = await lc.initialize_image_upload("tok", owner_urn="urn:li:person:s")

    assert result.upload_url == "https://upload.linkedin.example/x"
    assert result.image_urn == "urn:li:image:ABC123"
    assert result.upload_url_expires_at == 1700000000000
    assert captured["url"] == lc.INITIALIZE_UPLOAD_URL
    assert captured["headers"]["authorization"] == "Bearer tok"
    assert captured["headers"]["x-restli-protocol-version"] == "2.0.0"
    assert "linkedin-version" in captured["headers"]
    assert captured["body"] == {"initializeUploadRequest": {"owner": "urn:li:person:s"}}


async def test_initialize_image_upload_non_200_raises(patch_httpx):
    patch_httpx(lambda req: httpx.Response(403, text="forbidden"))
    with pytest.raises(lc.LinkedInAPIError) as ei:
        await lc.initialize_image_upload("tok", owner_urn="urn:li:person:x")
    assert ei.value.status == 403
    assert "forbidden" in ei.value.body


async def test_initialize_image_upload_missing_field_raises(patch_httpx):
    patch_httpx(lambda req: httpx.Response(200, json={"value": {}}))
    with pytest.raises(lc.LinkedInAPIError, match="missing field"):
        await lc.initialize_image_upload("tok", owner_urn="urn:li:person:x")


# --- upload_image_binary ---


async def test_upload_image_binary_puts_bytes(patch_httpx):
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["method"] = req.method
        captured["url"] = str(req.url)
        captured["content_type"] = req.headers.get("content-type")
        captured["body"] = req.content
        return httpx.Response(201)

    patch_httpx(handler)
    await lc.upload_image_binary("https://upload.example/abc", png_bytes=b"\x89PNG_data")

    assert captured["method"] == "PUT"
    assert captured["url"] == "https://upload.example/abc"
    assert captured["content_type"] == "application/octet-stream"
    assert captured["body"] == b"\x89PNG_data"


async def test_upload_image_binary_failure_raises(patch_httpx):
    patch_httpx(lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(lc.LinkedInAPIError) as ei:
        await lc.upload_image_binary("https://upload.example/abc", png_bytes=b"x")
    assert ei.value.status == 500


# --- upload_image (composed) ---


async def test_upload_image_composes_init_then_put(patch_httpx):
    calls: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append({"method": req.method, "url": str(req.url)})
        if req.method == "POST":
            return httpx.Response(
                200,
                json={
                    "value": {
                        "uploadUrl": "https://upload.example/zzz",
                        "image": "urn:li:image:ZZZ",
                        "uploadUrlExpiresAt": 0,
                    }
                },
            )
        return httpx.Response(201)

    patch_httpx(handler)
    urn = await lc.upload_image(
        "tok", owner_urn="urn:li:person:s", png_bytes=b"png-bytes"
    )

    assert urn == "urn:li:image:ZZZ"
    assert [c["method"] for c in calls] == ["POST", "PUT"]
    assert calls[1]["url"] == "https://upload.example/zzz"


# --- payload builders ---


def test_build_text_post_payload_shape():
    p = lc.build_text_post_payload(author="urn:li:person:s", commentary="hello world")
    assert p["author"] == "urn:li:person:s"
    assert p["commentary"] == "hello world"
    assert p["visibility"] == "PUBLIC"
    assert p["lifecycleState"] == "PUBLISHED"
    assert p["isReshareDisabledByAuthor"] is False
    assert p["distribution"]["feedDistribution"] == "MAIN_FEED"
    assert "content" not in p


def test_build_image_post_payload_includes_media():
    p = lc.build_image_post_payload(
        author="urn:li:person:s",
        commentary="caption",
        image_urn="urn:li:image:X",
        alt_text="alt",
    )
    assert p["content"]["media"]["id"] == "urn:li:image:X"
    assert p["content"]["media"]["altText"] == "alt"


def test_build_image_post_payload_omits_alt_when_none():
    p = lc.build_image_post_payload(
        author="urn:li:person:s", commentary="c", image_urn="urn:li:image:X"
    )
    assert "altText" not in p["content"]["media"]


def test_build_multi_image_post_payload():
    p = lc.build_multi_image_post_payload(
        author="urn:li:person:s",
        commentary="carousel",
        images=[("urn:li:image:1", "alt1"), ("urn:li:image:2", None)],
    )
    images = p["content"]["multiImage"]["images"]
    assert len(images) == 2
    assert images[0] == {"id": "urn:li:image:1", "altText": "alt1"}
    assert images[1] == {"id": "urn:li:image:2"}


def test_build_multi_image_rejects_too_few():
    with pytest.raises(ValueError, match="2-20"):
        lc.build_multi_image_post_payload(
            author="a", commentary="c", images=[("urn:li:image:1", None)]
        )


def test_build_multi_image_rejects_too_many():
    with pytest.raises(ValueError, match="2-20"):
        lc.build_multi_image_post_payload(
            author="a",
            commentary="c",
            images=[(f"urn:li:image:{i}", None) for i in range(21)],
        )


# --- create_post ---


async def test_create_post_returns_urn_from_header(patch_httpx):
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.content)
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:9999"})

    patch_httpx(handler)
    urn = await lc.create_post(
        "tok", lc.build_text_post_payload(author="urn:li:person:s", commentary="hi")
    )

    assert urn == "urn:li:share:9999"
    assert captured["url"] == lc.POSTS_URL
    assert captured["headers"]["authorization"] == "Bearer tok"
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["body"]["commentary"] == "hi"


async def test_create_post_non_201_raises(patch_httpx):
    patch_httpx(lambda req: httpx.Response(422, text="bad"))
    with pytest.raises(lc.LinkedInAPIError) as ei:
        await lc.create_post("tok", {"author": "a", "commentary": "x"})
    assert ei.value.status == 422


async def test_create_post_missing_restli_id_raises(patch_httpx):
    patch_httpx(lambda req: httpx.Response(201))
    with pytest.raises(lc.LinkedInAPIError, match="x-restli-id"):
        await lc.create_post("tok", {"author": "a", "commentary": "x"})


# --- token staleness ---


def test_is_token_stale_when_close_to_expiry():
    soon = datetime.now(tz=timezone.utc) + timedelta(minutes=1)
    assert lc._is_token_stale(soon) is True


def test_is_token_stale_when_far_from_expiry():
    later = datetime.now(tz=timezone.utc) + timedelta(hours=1)
    assert lc._is_token_stale(later) is False


def test_is_token_stale_handles_naive_datetime():
    # Treat naive datetimes as UTC (defensive — DB rows should be tz-aware but
    # some drivers strip tzinfo).
    naive_soon = (datetime.now(tz=timezone.utc) + timedelta(minutes=1)).replace(tzinfo=None)
    assert lc._is_token_stale(naive_soon) is True
