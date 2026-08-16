"""Happy-path test for RSSFetcher with a MockTransport-stubbed network."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.models.base import TrendSource
from app.retrieval.rss import MAX_ENTRIES_PER_FEED, RSSFetcher


def _rss_xml(items: list[dict]) -> str:
    item_xml = "\n".join(
        f"""
        <item>
            <title>{i['title']}</title>
            <link>{i['link']}</link>
            <guid>{i.get('guid', i['link'])}</guid>
            <pubDate>{i['pub_date']}</pubDate>
            <description>{i.get('summary', '')}</description>
        </item>
        """
        for i in items
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://test.example.com</link>
    <description>Test</description>
    {item_xml}
  </channel>
</rss>
"""


def _fmt(dt: datetime) -> str:
    # RFC 822 format expected by RSS pubDate
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


@pytest.fixture
def patch_rss_client(monkeypatch):
    """Patches httpx.AsyncClient inside app.retrieval.rss to use a MockTransport.
    Caller supplies a callable `handler(request) -> Response`."""

    def _apply(handler):
        from app.retrieval import rss as rss_mod

        real_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(rss_mod.httpx, "AsyncClient", factory)

    return _apply


async def test_happy_path_parses_entries(patch_rss_client):
    now = datetime.now(timezone.utc)
    body = _rss_xml(
        [
            {
                "title": "Fresh post",
                "link": "https://feed.example.com/fresh",
                "pub_date": _fmt(now - timedelta(days=1)),
                "summary": "A fresh post about something",
            },
            {
                "title": "Slightly older",
                "link": "https://feed.example.com/older",
                "pub_date": _fmt(now - timedelta(days=3)),
            },
        ]
    )
    patch_rss_client(
        lambda req: httpx.Response(200, text=body, headers={"ETag": "v1"})
    )

    fetcher = RSSFetcher(feeds=["https://feed.example.com/rss"])
    items = await fetcher.fetch()

    assert len(items) == 2
    assert all(i.source == TrendSource.rss for i in items)
    titles = {i.title for i in items}
    assert titles == {"Fresh post", "Slightly older"}
    # ETag captured for future If-None-Match
    assert fetcher._cache["https://feed.example.com/rss"].etag == "v1"


async def test_age_cutoff_drops_old_entries(patch_rss_client):
    now = datetime.now(timezone.utc)
    body = _rss_xml(
        [
            {
                "title": "Recent",
                "link": "https://feed.example.com/recent",
                "pub_date": _fmt(now - timedelta(days=5)),
            },
            {
                "title": "Ancient",
                "link": "https://feed.example.com/ancient",
                "pub_date": _fmt(now - timedelta(days=200)),
            },
        ]
    )
    patch_rss_client(lambda req: httpx.Response(200, text=body))

    items = await RSSFetcher(feeds=["https://feed.example.com/rss"]).fetch()
    assert len(items) == 1
    assert items[0].title == "Recent"


async def test_per_feed_cap_truncates(patch_rss_client):
    now = datetime.now(timezone.utc)
    # Build more entries than the cap.
    body = _rss_xml(
        [
            {
                "title": f"Entry {i}",
                "link": f"https://feed.example.com/{i}",
                "pub_date": _fmt(now - timedelta(hours=i)),
            }
            for i in range(MAX_ENTRIES_PER_FEED + 10)
        ]
    )
    patch_rss_client(lambda req: httpx.Response(200, text=body))

    items = await RSSFetcher(feeds=["https://feed.example.com/rss"]).fetch()
    assert len(items) == MAX_ENTRIES_PER_FEED


async def test_304_not_modified_returns_empty(patch_rss_client):
    patch_rss_client(lambda req: httpx.Response(304))
    items = await RSSFetcher(feeds=["https://feed.example.com/rss"]).fetch()
    assert items == []


async def test_one_feed_failing_does_not_break_the_batch(patch_rss_client):
    now = datetime.now(timezone.utc)
    ok_body = _rss_xml(
        [
            {
                "title": "From ok feed",
                "link": "https://ok.example.com/p",
                "pub_date": _fmt(now - timedelta(days=1)),
            }
        ]
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if "bad" in str(req.url):
            return httpx.Response(500)
        return httpx.Response(200, text=ok_body)

    patch_rss_client(handler)

    fetcher = RSSFetcher(
        feeds=[
            "https://bad.example.com/rss",
            "https://ok.example.com/rss",
        ]
    )
    items = await fetcher.fetch()
    assert len(items) == 1
    assert items[0].title == "From ok feed"
