"""Happy-path test for HackerNewsFetcher with MockTransport-stubbed network."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.models.base import TrendSource
from app.retrieval.hackernews import HackerNewsFetcher

NOW = int(datetime.now(timezone.utc).timestamp())


def _make_item(hid: int, **kwargs) -> dict:
    base = {
        "id": hid,
        "type": "story",
        "title": f"Story {hid}",
        "url": f"https://example.com/{hid}",
        "score": 100 + hid,
        "by": "alice",
        "descendants": hid,
        "time": NOW - hid,  # recent by default — hid seconds ago, still fresh
    }
    base.update(kwargs)
    return base


def _make_handler(
    top_ids: list[int], best_ids: list[int], items: dict[int, dict | None]
):
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url.endswith("/topstories.json"):
            return httpx.Response(200, text=json.dumps(top_ids))
        if url.endswith("/beststories.json"):
            return httpx.Response(200, text=json.dumps(best_ids))
        # item/<id>.json
        if "/item/" in url:
            hid = int(url.rsplit("/", 1)[-1].split(".")[0])
            data = items.get(hid)
            return httpx.Response(200, text=json.dumps(data))
        return httpx.Response(404)

    return handler


@pytest.fixture
def patch_hn_client(monkeypatch):
    def _apply(handler):
        from app.retrieval import hackernews as hn_mod

        real_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(hn_mod.httpx, "AsyncClient", factory)

    return _apply


async def test_happy_path_pulls_top_and_best(patch_hn_client):
    items = {1: _make_item(1), 2: _make_item(2), 3: _make_item(3)}
    patch_hn_client(_make_handler([1, 2], [2, 3], items))

    result = await HackerNewsFetcher(top_n=2, best_n=2).fetch()
    assert len(result) == 3  # 2 dedup'd via shared id
    sources = {r.source for r in result}
    assert sources == {TrendSource.hackernews}
    ids = {r.source_id for r in result}
    assert ids == {"1", "2", "3"}


async def test_skips_dead_deleted_and_non_story(patch_hn_client):
    items = {
        1: _make_item(1),
        2: _make_item(2, dead=True),
        3: _make_item(3, deleted=True),
        4: _make_item(4, type="comment"),
        5: None,  # API returned null
    }
    patch_hn_client(_make_handler([1, 2, 3, 4, 5], [], items))

    result = await HackerNewsFetcher(top_n=5, best_n=0).fetch()
    assert {r.source_id for r in result} == {"1"}


async def test_falls_back_to_hn_url_when_story_has_no_url(patch_hn_client):
    items = {42: _make_item(42, url=None)}
    patch_hn_client(_make_handler([42], [], items))

    result = await HackerNewsFetcher(top_n=1, best_n=0).fetch()
    assert len(result) == 1
    assert result[0].url == "https://news.ycombinator.com/item?id=42"


async def test_score_captured_in_payload_and_top_field(patch_hn_client):
    items = {7: _make_item(7, score=250)}
    patch_hn_client(_make_handler([7], [], items))

    result = await HackerNewsFetcher(top_n=1, best_n=0).fetch()
    assert result[0].score == 250.0
    assert result[0].raw_payload["by"] == "alice"
    assert result[0].raw_payload["descendants"] == 7


async def test_age_cutoff_drops_stories_older_than_retention(patch_hn_client):
    stale_time = int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp())
    items = {
        1: _make_item(1),  # fresh (default `time`)
        2: _make_item(2, time=stale_time),
    }
    patch_hn_client(_make_handler([1, 2], [], items))

    result = await HackerNewsFetcher(top_n=2, best_n=0).fetch()
    assert {r.source_id for r in result} == {"1"}
