"""Retrieval orchestrator.

Runs all enabled fetchers in source-priority order, dedupes the combined
batch, and bulk-inserts into the `trends` table with ON CONFLICT DO NOTHING
against (source, source_id) so re-runs are idempotent.

Source-priority order matters: when the same story appears in multiple
sources, the dedupe layer keeps the FIRST seen version. RSS is listed first
because curated long-form (Stratechery, First Round, etc.) is higher-signal
than an aggregator headline.

Reddit fetcher import is intentionally left out — re-enable when the Reddit
Data API access is approved.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.models import Trend
from app.retrieval.base import Fetcher, TrendItem
from app.retrieval.dedupe import dedupe
from app.retrieval.hackernews import HackerNewsFetcher
from app.retrieval.rss import RSSFetcher

# from app.retrieval.reddit import RedditFetcher  # ACTIVATE on Reddit Data API approval

log = structlog.get_logger()


def _enabled_fetchers() -> list[Fetcher]:
    return [
        RSSFetcher(),
        HackerNewsFetcher(),
        # RedditFetcher(),
    ]


async def _fetch_all(
    fetchers: list[Fetcher],
) -> tuple[list[TrendItem], dict[str, int]]:
    all_items: list[TrendItem] = []
    counts: dict[str, int] = {}
    for f in fetchers:
        try:
            items = await f.fetch()
        except Exception as e:
            log.warning(
                "retrieval.fetcher_failed", source=f.source.value, error=str(e)
            )
            items = []
        counts[f.source.value] = len(items)
        all_items.extend(items)
    return all_items, counts


def _to_row(item: TrendItem) -> dict[str, Any]:
    return {
        "source": item.source,
        "source_id": item.source_id,
        "title": item.title,
        "url": item.url,
        "summary": item.summary,
        "score": int(item.score) if item.score is not None else None,
        "raw_payload": item.raw_payload or {},
        "fetched_at": item.fetched_at or datetime.now(timezone.utc),
    }


async def run_retrieval() -> dict[str, Any]:
    """Run all enabled fetchers, dedupe, bulk-insert.
    Returns a summary dict for callers/logs."""
    fetchers = _enabled_fetchers()
    log.info(
        "retrieval.start", fetchers=[f.source.value for f in fetchers]
    )

    items, per_source = await _fetch_all(fetchers)
    deduped = dedupe(items)

    inserted = 0
    if deduped:
        rows = [_to_row(i) for i in deduped]
        async with AsyncSessionLocal() as session:
            stmt = (
                pg_insert(Trend)
                .values(rows)
                .on_conflict_do_nothing(
                    index_elements=["source", "source_id"]
                )
                .returning(Trend.id)
            )
            result = await session.execute(stmt)
            inserted = len(result.scalars().all())
            await session.commit()

    summary = {
        "fetched": len(items),
        "deduped": len(deduped),
        "inserted": inserted,
        "per_source": per_source,
    }
    log.info("retrieval.done", **summary)
    return summary
