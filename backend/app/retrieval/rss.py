"""RSSFetcher — pulls from a locked list of high-signal feeds.

Polite: sends a real User-Agent, honors ETag / Last-Modified between runs
(in-memory cache — survives a single process lifetime; the orchestrator's
DB-level (source, source_id) constraint catches dupes across restarts).

Feed list verified live in May 2026. Update DEFAULT_FEEDS here, not at call
sites. Anthropic + Indie Hackers were considered but neither publishes an
official RSS feed; Hugging Face replaces Anthropic and HackerNews covers
indie/builder signal.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
import structlog

from app.models.base import TrendSource
from app.retrieval.base import Fetcher, TrendItem

log = structlog.get_logger()

USER_AGENT = "AutoPost/0.1 (+autopost retrieval bot)"

# Feed URLs verified live in May 2026. First Round Review removed — both
# candidate URLs (/rss, /feed.xml) return 404; their RSS appears to be
# discontinued. Anthropic also has no official feed; Hugging Face covers
# the "primary AI source" slot instead. Five feeds is intentionally tight.
DEFAULT_FEEDS: list[str] = [
    "https://stratechery.com/feed/",
    "https://stripe.com/blog/feed.rss",
    "https://newsletter.pragmaticengineer.com/feed",
    "https://openai.com/news/rss.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://simonwillison.net/atom/everything/",
    "https://www.latent.space/feed",
]

# Per-feed item cap and age cutoff. Most of our feeds publish their full
# backlog over RSS (Stratechery returns ~1,500 entries; Hugging Face ~250).
# Without these caps the unconsumed-trends pool fills with years-old posts.
MAX_ENTRIES_PER_FEED = 25
MAX_ENTRY_AGE = timedelta(days=90)


@dataclass
class _FeedCache:
    etag: str | None = None
    last_modified: str | None = None


class RSSFetcher(Fetcher):
    source = TrendSource.rss

    def __init__(self, feeds: list[str] | None = None, *, timeout: float = 15.0):
        self.feeds = feeds or DEFAULT_FEEDS
        self.timeout = timeout
        self._cache: dict[str, _FeedCache] = {}

    async def fetch(self) -> list[TrendItem]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            results = await asyncio.gather(
                *(self._fetch_one(client, url) for url in self.feeds),
                return_exceptions=True,
            )

        items: list[TrendItem] = []
        for feed_url, result in zip(self.feeds, results):
            if isinstance(result, Exception):
                log.warning("rss.feed_failed", feed=feed_url, error=str(result))
                continue
            items.extend(result)
        log.info("rss.fetch_complete", feeds=len(self.feeds), items=len(items))
        return items

    async def _fetch_one(
        self, client: httpx.AsyncClient, url: str
    ) -> list[TrendItem]:
        cache = self._cache.setdefault(url, _FeedCache())
        headers: dict[str, str] = {}
        if cache.etag:
            headers["If-None-Match"] = cache.etag
        if cache.last_modified:
            headers["If-Modified-Since"] = cache.last_modified

        resp = await client.get(url, headers=headers)
        if resp.status_code == 304:
            log.debug("rss.not_modified", feed=url)
            return []
        resp.raise_for_status()

        cache.etag = resp.headers.get("ETag")
        cache.last_modified = resp.headers.get("Last-Modified")

        parsed = await asyncio.to_thread(feedparser.parse, resp.content)
        cutoff = datetime.now(timezone.utc) - MAX_ENTRY_AGE
        items: list[TrendItem] = []
        for entry in parsed.entries[:MAX_ENTRIES_PER_FEED]:
            if not entry.get("link"):
                continue
            item = self._to_item(url, entry)
            if item.fetched_at is not None and item.fetched_at < cutoff:
                continue
            items.append(item)
        return items

    def _to_item(self, feed_url: str, entry) -> TrendItem:
        title = (entry.get("title") or "").strip()[:1024]
        link = entry.get("link", "").strip()
        summary = (entry.get("summary") or "").strip() or None
        if summary:
            summary = summary[:4000]

        source_id = (
            entry.get("id")
            or entry.get("guid")
            or hashlib.sha1(link.encode()).hexdigest()
        )

        published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
        fetched_at: datetime | None = None
        if published_struct:
            fetched_at = datetime(*published_struct[:6], tzinfo=timezone.utc)

        return TrendItem(
            source=self.source,
            source_id=str(source_id)[:512],
            title=title,
            url=link,
            summary=summary,
            score=None,
            raw_payload={
                "feed_url": feed_url,
                "author": entry.get("author"),
                "tags": [
                    t.get("term") for t in entry.get("tags", []) if t.get("term")
                ],
                "published": entry.get("published"),
            },
            fetched_at=fetched_at,
        )
