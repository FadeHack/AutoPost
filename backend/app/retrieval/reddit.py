"""RedditFetcher — written but DISABLED in the orchestrator until Reddit
Data API access is approved.

To activate after approval:
  1. Confirm REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET / REDDIT_USER_AGENT
     are filled in backend/.env
  2. In backend/app/retrieval/orchestrator.py (Chunk B), uncomment the
     RedditFetcher() entry in the fetcher list
  3. Tune DEFAULT_SUBREDDITS below for current voice/topic fit

PRAW is synchronous; we wrap calls in asyncio.to_thread so the orchestrator
can stay async.
"""
from __future__ import annotations

import asyncio

import praw
import structlog

from app.config import settings
from app.models.base import TrendSource
from app.retrieval.base import Fetcher, TrendItem

log = structlog.get_logger()

DEFAULT_SUBREDDITS: list[str] = [
    "startups",
    "Entrepreneur",
    "indiehackers",
    "MachineLearning",
    "ClaudeAI",
    "ChatGPT",
    "programming",
    "SaaS",
]


class RedditFetcher(Fetcher):
    source = TrendSource.reddit

    def __init__(
        self, subreddits: list[str] | None = None, *, hot_limit: int = 25
    ):
        self.subreddits = subreddits or DEFAULT_SUBREDDITS
        self.hot_limit = hot_limit

    async def fetch(self) -> list[TrendItem]:
        return await asyncio.to_thread(self._fetch_sync)

    def _fetch_sync(self) -> list[TrendItem]:
        reddit = praw.Reddit(
            client_id=settings.REDDIT_CLIENT_ID,
            client_secret=settings.REDDIT_CLIENT_SECRET,
            user_agent=settings.REDDIT_USER_AGENT or "AutoPost/0.1",
            check_for_async=False,
        )
        reddit.read_only = True

        items: list[TrendItem] = []
        for sub in self.subreddits:
            try:
                for post in reddit.subreddit(sub).hot(limit=self.hot_limit):
                    if post.stickied:
                        continue
                    items.append(self._to_item(post, sub))
            except Exception as e:
                log.warning("reddit.subreddit_failed", sub=sub, error=str(e))
        log.info("reddit.fetch_complete", items=len(items))
        return items

    def _to_item(self, post, subreddit: str) -> TrendItem:
        is_self = bool(getattr(post, "is_self", False))
        url = (
            f"https://reddit.com{post.permalink}"
            if is_self
            else post.url
        )
        summary = (post.selftext or "")[:4000] if is_self else None

        return TrendItem(
            source=self.source,
            source_id=post.id,
            title=post.title[:1024],
            url=url,
            summary=summary or None,
            score=float(post.score or 0),
            raw_payload={
                "subreddit": subreddit,
                "author": str(post.author) if post.author else None,
                "num_comments": post.num_comments,
                "created_utc": post.created_utc,
                "permalink": f"https://reddit.com{post.permalink}",
                "over_18": post.over_18,
            },
        )
