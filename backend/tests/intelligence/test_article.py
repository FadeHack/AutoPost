"""Tests for the article extractor."""
from __future__ import annotations

import httpx
import pytest

from app.intelligence import article


_SAMPLE_HTML = """<!doctype html>
<html><head><title>Example</title></head>
<body>
<article>
<h1>Some headline</h1>
<p>This is the first real paragraph of the article body that trafilatura should keep.</p>
<p>And here is a second meaningful paragraph with more substantive content to extract.</p>
</article>
<footer>Boilerplate footer that should get stripped.</footer>
</body></html>
"""


@pytest.fixture
def patch_httpx(monkeypatch):
    def _apply(handler):
        real_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(article.httpx, "AsyncClient", factory)

    return _apply


async def test_happy_path_extracts_clean_text(patch_httpx):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_SAMPLE_HTML)

    patch_httpx(handler)
    out = await article.fetch_article("https://example.com/post")
    assert out is not None
    assert "first real paragraph" in out
    assert "second meaningful paragraph" in out
    # Boilerplate footer stripped
    assert "Boilerplate footer" not in out


async def test_non_200_returns_none(patch_httpx):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    patch_httpx(handler)
    assert await article.fetch_article("https://example.com/missing") is None


async def test_network_error_returns_none(patch_httpx):
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns fail")

    patch_httpx(handler)
    assert await article.fetch_article("https://example.com/down") is None


async def test_unextractable_html_returns_none(patch_httpx):
    def handler(req: httpx.Request) -> httpx.Response:
        # No real content — trafilatura should return None / empty.
        return httpx.Response(200, text="<html><body></body></html>")

    patch_httpx(handler)
    assert await article.fetch_article("https://example.com/empty") is None


async def test_truncates_to_max_chars(monkeypatch, patch_httpx):
    long_text = "x" * (article.MAX_CHARS + 5000)

    async def fake_extract(html: str) -> str:
        return long_text

    # Patch the sync extractor with a sync function (asyncio.to_thread will run it).
    monkeypatch.setattr(article, "_extract", lambda html: long_text)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>doesn't matter</body></html>")

    patch_httpx(handler)
    out = await article.fetch_article("https://example.com/long")
    assert out is not None
    assert len(out) == article.MAX_CHARS
