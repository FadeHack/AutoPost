"""HackerNewsFetcher — top + best stories via the official Firebase API.

API contract verified May 2026 against https://github.com/HackerNews/API.
Base: hacker-news.firebaseio.com/v0
No auth, no rate limit. Stories without a URL (Ask HN / Show HN text posts)
get the HN item URL as fallback so they still link somewhere.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import structlog

from app.config import settings
from app.models.base import TrendSource
from app.retrieval.base import Fetcher, TrendItem

log = structlog.get_logger()

HN_BASE = "https://hacker-news.firebaseio.com/v0"
USER_AGENT = "AutoPost/0.1"
# Mirrors `settings.TREND_RETENTION_DAYS` — RSS already age-filters at ingest
# (see rss.py); HN's `top`/`best` endpoints can still surface an older
# evergreen story, so apply the same cutoff here (2026-08-16).
MAX_ITEM_AGE = timedelta(days=settings.TREND_RETENTION_DAYS)


class HackerNewsFetcher(Fetcher):
    source = TrendSource.hackernews

    def __init__(
        self, *, top_n: int = 30, best_n: int = 20, timeout: float = 15.0
    ):
        self.top_n = top_n
        self.best_n = best_n
        self.timeout = timeout

    async def fetch(self) -> list[TrendItem]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            top_ids, best_ids = await asyncio.gather(
                self._ids(client, "topstories"),
                self._ids(client, "beststories"),
            )

            # Dedup ID set while preserving insertion order
            wanted: dict[int, None] = {}
            for hid in top_ids[: self.top_n]:
                wanted[hid] = None
            for hid in best_ids[: self.best_n]:
                wanted[hid] = None

            results = await asyncio.gather(
                *(self._item(client, hid) for hid in wanted),
                return_exceptions=True,
            )

        items: list[TrendItem] = []
        for r in results:
            if isinstance(r, Exception):
                log.warning("hn.item_failed", error=str(r))
                continue
            if r is not None:
                items.append(r)
        log.info("hn.fetch_complete", items=len(items))
        return items

    async def _ids(self, client: httpx.AsyncClient, endpoint: str) -> list[int]:
        resp = await client.get(f"{HN_BASE}/{endpoint}.json")
        resp.raise_for_status()
        return resp.json() or []

    async def _item(
        self, client: httpx.AsyncClient, hid: int
    ) -> TrendItem | None:
        resp = await client.get(f"{HN_BASE}/item/{hid}.json")
        resp.raise_for_status()
        data = resp.json()
        if not data or data.get("dead") or data.get("deleted"):
            return None
        if data.get("type") != "story":
            return None

        item_time = data.get("time")
        if item_time is not None:
            posted_at = datetime.fromtimestamp(item_time, tz=timezone.utc)
            if datetime.now(timezone.utc) - posted_at > MAX_ITEM_AGE:
                return None

        title = (data.get("title") or "").strip()[:1024]
        url = data.get("url") or f"https://news.ycombinator.com/item?id={hid}"

        return TrendItem(
            source=self.source,
            source_id=str(hid),
            title=title,
            url=url,
            summary=None,
            score=float(data.get("score") or 0),
            raw_payload={
                "by": data.get("by"),
                "descendants": data.get("descendants"),
                "time": data.get("time"),
                "type": data.get("type"),
                "hn_url": f"https://news.ycombinator.com/item?id={hid}",
            },
        )
