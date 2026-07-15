"""Tests for the pure helpers in app/api/posts.py.

Endpoint behavior is covered by manual end-to-end smoke against Supabase,
matching the pattern used elsewhere in this repo (renderer, generator). Here
we only test the small bits of pure logic that have non-trivial branching."""
from __future__ import annotations

import base64

import pytest

from app.api.posts import (
    MAX_TAG_LENGTH,
    MAX_TAGS,
    _image_dimensions,
    normalize_tags,
)

# 1x1 pixel images, base64-encoded, one per supported upload format.
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)
_GIF_1x1 = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
_JPEG_10x10 = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAAKAAoBAREA/8QAFAAB"
    "AAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAT8AH//Z"
)


class TestImageDimensions:
    def test_png(self) -> None:
        assert _image_dimensions(_PNG_1x1) == (1, 1)

    def test_gif(self) -> None:
        assert _image_dimensions(_GIF_1x1) == (1, 1)

    def test_jpeg_scans_to_sof_marker(self) -> None:
        assert _image_dimensions(_JPEG_10x10) == (10, 10)

    def test_unrecognized_bytes_raise(self) -> None:
        with pytest.raises(ValueError):
            _image_dimensions(b"not an image at all")


class TestNormalizeTags:
    def test_lowercases_and_strips_hash(self) -> None:
        assert normalize_tags(["Python", "#AI", " GoLang "]) == [
            "python",
            "ai",
            "golang",
        ]

    def test_drops_empty_and_whitespace(self) -> None:
        assert normalize_tags(["", "  ", "#", "foo"]) == ["foo"]

    def test_dedupes_preserving_first_order(self) -> None:
        # "Python" arrives before "python" so "python" wins.
        assert normalize_tags(["Python", "python", "PYTHON", "ai"]) == [
            "python",
            "ai",
        ]

    def test_dedupes_after_hash_strip(self) -> None:
        # "#ai" and "ai" normalize to the same thing.
        assert normalize_tags(["#ai", "ai"]) == ["ai"]

    def test_caps_at_max_tags(self) -> None:
        raw = [f"tag{i}" for i in range(MAX_TAGS + 5)]
        out = normalize_tags(raw)
        assert len(out) == MAX_TAGS
        assert out[0] == "tag0"

    def test_truncates_overlong_tag(self) -> None:
        long = "x" * (MAX_TAG_LENGTH + 20)
        out = normalize_tags([long])
        assert len(out) == 1
        assert len(out[0]) == MAX_TAG_LENGTH

    def test_skips_non_strings(self) -> None:
        # Type-system says list[str] but JSON can deliver anything; the
        # endpoint passes through whatever Pydantic accepts, so be defensive.
        assert normalize_tags(["ok", None, 42, {"x": 1}, "fine"]) == [  # type: ignore[list-item]
            "ok",
            "fine",
        ]

    def test_empty_input_returns_empty(self) -> None:
        assert normalize_tags([]) == []
