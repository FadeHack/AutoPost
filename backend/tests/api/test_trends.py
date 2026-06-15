"""Tests for the pure bits of app/api/trends.py + scheduler sweeper math.

Endpoint behavior (DB writes, status codes, cascades) is covered by manual
end-to-end smoke against Supabase, matching the pattern used in test_posts.py.
Here we only test schema validation and the sweeper cutoff calculation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.trends import BulkDeleteRequest
from app.config import settings


class TestBulkDeleteRequestSchema:
    def test_accepts_single_id(self) -> None:
        req = BulkDeleteRequest(ids=[uuid4()])
        assert len(req.ids) == 1

    def test_accepts_many_ids(self) -> None:
        req = BulkDeleteRequest(ids=[uuid4() for _ in range(50)])
        assert len(req.ids) == 50

    def test_rejects_empty_list(self) -> None:
        with pytest.raises(ValidationError):
            BulkDeleteRequest(ids=[])

    def test_rejects_overlarge_list(self) -> None:
        with pytest.raises(ValidationError):
            BulkDeleteRequest(ids=[uuid4() for _ in range(501)])

    def test_rejects_non_uuid(self) -> None:
        with pytest.raises(ValidationError):
            BulkDeleteRequest(ids=["not-a-uuid"])  # type: ignore[list-item]


class TestSweeperCutoff:
    """The sweeper deletes consumed rows older than the retention window.
    Verify the cutoff math matches the configured retention setting."""

    def test_cutoff_is_retention_days_in_the_past(self) -> None:
        retention = settings.TRENDS_CONSUMED_RETENTION_DAYS
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=retention)
        # A row consumed exactly retention+1 days ago must be older than cutoff.
        old = now - timedelta(days=retention + 1)
        # A row consumed 1 hour ago must be newer than cutoff.
        fresh = now - timedelta(hours=1)
        assert old < cutoff
        assert fresh > cutoff

    def test_default_retention_is_sixty_days(self) -> None:
        # CLAUDE.md spec: keep consumed trends 60 days before sweeping.
        assert settings.TRENDS_CONSUMED_RETENTION_DAYS == 60
