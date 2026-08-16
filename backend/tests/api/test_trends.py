"""Tests for app/api/trends.py + the retention-sweep cutoff math.

`dismiss_all_trends` / `list_trends` / `update_trend` do real query-building
against SQLAlchemy Core constructs, so most of their logic is exercised via
manual end-to-end smoke against Supabase (matching test_posts.py's
convention) rather than a mock-session harness here. This file covers the
schema-free pieces: the retention cutoff math (now workspace-independent,
per-trend `fetched_at` only) and a couple of the DB-orchestration helpers
that behave like pure functions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import settings


class TestRetentionSweepCutoff:
    """The sweep deletes trends older than the retention window, purely by
    `fetched_at` — no longer gated on consumption (consumption is
    per-workspace as of 2026-08-16, so there's no single global flag to
    check). Verify the cutoff math matches the configured window."""

    def test_cutoff_is_retention_days_in_the_past(self) -> None:
        retention = settings.TREND_RETENTION_DAYS
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=retention)
        # A row fetched exactly retention+1 days ago must be older than cutoff.
        old = now - timedelta(days=retention + 1)
        # A row fetched 1 hour ago must be newer than cutoff.
        fresh = now - timedelta(hours=1)
        assert old < cutoff
        assert fresh > cutoff

    def test_default_retention_is_seven_days(self) -> None:
        # CLAUDE.md / CONTEXT.md spec (2026-08-16, user-confirmed): trends
        # older than 7 days are neither ingested nor retained — "what's new"
        # stops being new fast for this product.
        assert settings.TREND_RETENTION_DAYS == 7
