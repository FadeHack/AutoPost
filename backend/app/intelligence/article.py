"""On-demand article body extraction.

Generator calls `fetch_article(url)` per picked trend. trafilatura turns the
HTML into clean text; we cap at 8K chars (≈2K tokens) so the LLM stays
focused on the article body, not boilerplate. Any failure (paywall, 404,
non-article page) returns None and the caller falls back to title + summary.
"""
from __future__ import annotations

import asyncio

import httpx
import structlog
import trafilatura

log = structlog.get_logger(__name__)

MAX_CHARS = 2500
FETCH_TIMEOUT = 10.0
USER_AGENT = "AutoPost/0.1 (+article-fetcher)"


def _extract(html: str) -> str | None:
    try:
        return trafilatura.extract(
            html,
            favor_precision=True,
            include_comments=False,
            include_tables=False,
        )
    except Exception:
        return None


async def fetch_article(url: str) -> str | None:
    """Fetch + extract. Returns clean text (≤ MAX_CHARS) or None on any failure."""
    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError as e:
        log.info("article.fetch.error", url=url, err=type(e).__name__)
        return None
    except Exception as e:
        log.warning("article.fetch.unexpected", url=url, err=type(e).__name__)
        return None

    if resp.status_code != 200:
        log.info("article.fetch.non_200", url=url, status=resp.status_code)
        return None

    text = await asyncio.to_thread(_extract, resp.text)
    if not text:
        log.info("article.extract.empty", url=url)
        return None

    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    return text
