"""RSSFetcher — pulls from a locked list of high-signal feeds.

Polite: sends a real User-Agent, honors ETag / Last-Modified between runs
(in-memory cache — survives a single process lifetime; the orchestrator's
DB-level (source, source_id) constraint catches dupes across restarts).

Feed list verified live in May 2026, extended + re-verified June 2026 for
Phase 12. Update DEFAULT_FEEDS here, not at call sites. Anthropic + Indie
Hackers were considered but neither publishes an official RSS feed; Hugging
Face replaces Anthropic and HackerNews covers indie/builder signal.

Phase 12 freshness pass (2026-06-17) — added feeds aimed at the new categories
(dev_tooling, product_postmortem, design_thinking). Each was fetched live and
confirmed publishing in 2026:
  - lethain.com (Will Larson, engineering leadership)  — newest 2026-06-15
  - jvns.ca (Julia Evans, hands-on engineering)        — newest 2026-05-15
  - nngroup.com (Nielsen Norman Group, UX/design)      — newest 2026-06-12
CUT per the freshness gate:
  - rachelbythebay — blocks non-browser bots (404 on feed AND site to our UA);
    an automated retrieval bot can't reliably read it, so the unique
    incident-writeup signal isn't worth a feed that won't fetch.
  - a16z.com/feed/ — 404, and its business/pricing angle duplicates the
    Stratechery + Stripe coverage already in the list.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
import structlog

from app.config import settings
from app.models.base import TrendSource
from app.retrieval.base import Fetcher, TrendItem

log = structlog.get_logger()

USER_AGENT = "AutoPost/0.1 (+autopost retrieval bot)"

# Feed URLs verified live in May 2026 (first 7), Phase 12 additions re-verified
# 2026-06-17 (last 3). First Round Review removed — both candidate URLs (/rss,
# /feed.xml) return 404; their RSS appears to be discontinued. Anthropic also
# has no official feed; Hugging Face covers the "primary AI source" slot.
DEFAULT_FEEDS: list[str] = [
    "https://stratechery.com/feed/",
    "https://stripe.com/blog/feed.rss",
    "https://newsletter.pragmaticengineer.com/feed",
    "https://openai.com/news/rss.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://simonwillison.net/atom/everything/",
    "https://www.latent.space/feed",
    # Phase 12 (dev_tooling / product_postmortem / design_thinking surface):
    "https://lethain.com/feeds/",
    "https://jvns.ca/atom.xml",
    "https://www.nngroup.com/feed/rss/",
]

# Per-feed item cap and age cutoff. Most of our feeds publish their full
# backlog over RSS (Stratechery returns ~1,500 entries; Hugging Face ~250).
# Without these caps the unconsumed-trends pool fills with years-old posts.
# Age cutoff mirrors `settings.TREND_RETENTION_DAYS` (2026-08-16,
# user-confirmed) — one number for "how old can a trend be, ever," shared
# with the DB-side retention sweep in scheduler/jobs.py so ingest and cleanup
# can't drift apart.
MAX_ENTRIES_PER_FEED = 25
MAX_ENTRY_AGE = timedelta(days=settings.TREND_RETENTION_DAYS)


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
