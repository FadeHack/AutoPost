"""Phase 12 Chunk A — per-platform prompt matrix lookup + Stage-2 rewrite.

No DB: the generator's prompt loaders take an AsyncSession and call
`session.execute(stmt)` then `.scalar_one_or_none()`. We drive them with a fake
session that hands back queued results, so we assert the lookup *logic*
(prefer-platform → fall-back-to-NULL → raise) without a live Postgres.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest  # noqa: F401  (asyncio_mode=auto picks up async tests)

from app.intelligence import generator
from app.models.base import Platform, PostCategory


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """Returns queued results in order; records how many executes happened."""

    def __init__(self, rows):
        self._queue = list(rows)
        self.executes = 0

    async def execute(self, _stmt):
        self.executes += 1
        return _FakeResult(self._queue.pop(0) if self._queue else None)


def _prompt(platform):
    return SimpleNamespace(
        id=uuid.uuid4(),
        platform=platform,
        body=f"{platform.value if platform else 'any'} voice prompt",
    )


class TestLoadActivePrompt:
    async def test_prefers_platform_variant(self):
        row = _prompt(Platform.linkedin)
        session = _FakeSession([row])
        out = await generator._load_active_prompt(
            session, PostCategory.founder_insight, platform=Platform.linkedin
        )
        assert out is row
        assert session.executes == 1  # found on the platform query, no fallback

    async def test_falls_back_to_null(self):
        null_row = _prompt(None)
        # First (platform) query misses, second (NULL) hits.
        session = _FakeSession([None, null_row])
        out = await generator._load_active_prompt(
            session, PostCategory.engineering_lesson, platform=Platform.mastodon
        )
        assert out is null_row
        assert session.executes == 2

    async def test_platform_none_skips_platform_query(self):
        null_row = _prompt(None)
        session = _FakeSession([null_row])
        out = await generator._load_active_prompt(
            session, PostCategory.founder_insight, platform=None
        )
        assert out is null_row
        assert session.executes == 1  # straight to the NULL query

    async def test_raises_when_neither_exists(self):
        session = _FakeSession([None, None])
        with pytest.raises(ValueError, match="No active prompt"):
            await generator._load_active_prompt(
                session, PostCategory.founder_insight, platform=Platform.threads
            )


class TestLoadPlatformPrompt:
    async def test_returns_row_when_present(self):
        row = _prompt(Platform.bluesky)
        session = _FakeSession([row])
        out = await generator._load_platform_prompt(
            session, PostCategory.founder_insight, Platform.bluesky
        )
        assert out is row

    async def test_returns_none_when_absent(self):
        session = _FakeSession([None])
        out = await generator._load_platform_prompt(
            session, PostCategory.founder_insight, Platform.instagram
        )
        assert out is None
        assert session.executes == 1  # no NULL fallback for the rewrite lookup


class TestPlatformCharLimits:
    def test_map_matches_publisher_caps(self):
        assert generator.PLATFORM_CHAR_LIMITS == {
            Platform.linkedin: 3000,
            Platform.bluesky: 300,
            Platform.mastodon: 500,
            Platform.threads: 500,
            Platform.instagram: 2200,
            Platform.x: 280,
        }


class TestRunPlatformRewrite:
    async def test_returns_cleaned_text_within_cap(self, monkeypatch):
        async def fake_chat(**_kwargs):
            return '"Sharp bluesky take. One line."'

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)
        out = await generator.run_platform_rewrite(
            prompt=_prompt(Platform.bluesky),
            source_text="long linkedin source",
            char_limit=generator.PLATFORM_CHAR_LIMITS[Platform.bluesky],
        )
        assert out == "Sharp bluesky take. One line."
        assert len(out) <= 300

    async def test_does_not_truncate_over_cap(self, monkeypatch):
        # A mis-tuned prompt over-shoots: we return it whole (orchestrator gate
        # fails loudly) rather than ship a mangled truncation.
        async def fake_chat(**_kwargs):
            return "x" * 420

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)
        out = await generator.run_platform_rewrite(
            prompt=_prompt(Platform.threads),
            source_text="src",
            char_limit=generator.PLATFORM_CHAR_LIMITS[Platform.threads],
        )
        assert len(out) == 420  # NOT clipped to 500-char cap

    async def test_instagram_long_caption_allowed(self, monkeypatch):
        # Instagram's 2200 cap is LONGER than a typical LinkedIn body — "compress"
        # is the wrong verb. A 1500-char caption is well within cap.
        async def fake_chat(**_kwargs):
            return "y" * 1500

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)
        out = await generator.run_platform_rewrite(
            prompt=_prompt(Platform.instagram),
            source_text="src",
            char_limit=generator.PLATFORM_CHAR_LIMITS[Platform.instagram],
        )
        assert len(out) == 1500 <= 2200
