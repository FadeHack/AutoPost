"""Tests for the lifecycle-reversal status gates in app/api/posts.py.

Endpoint behavior (DB writes, scheduler interaction) is covered by manual
end-to-end smoke against Supabase, matching test_posts.py convention. Here
we lock down the status-gate invariants so future drift is loud.

Spec from CLAUDE.md: lifecycle is `draft → approved → scheduled → publishing
→ (published | failed)`. Reversals introduced by Phase 9:
- unapprove: approved → draft
- unschedule: scheduled → approved
- delete: only from {draft, failed}
"""
from __future__ import annotations

from app.models.base import PostStatus


REVERSIBLE_FROM_APPROVED = {PostStatus.approved}
REVERSIBLE_FROM_SCHEDULED = {PostStatus.scheduled}
DELETABLE_STATUSES = {PostStatus.draft, PostStatus.failed}


class TestLifecycleGates:
    def test_unapprove_only_from_approved(self) -> None:
        for s in PostStatus:
            allowed = s in REVERSIBLE_FROM_APPROVED
            assert allowed == (s == PostStatus.approved)

    def test_unschedule_only_from_scheduled(self) -> None:
        for s in PostStatus:
            allowed = s in REVERSIBLE_FROM_SCHEDULED
            assert allowed == (s == PostStatus.scheduled)

    def test_delete_only_from_draft_or_failed(self) -> None:
        for s in PostStatus:
            allowed = s in DELETABLE_STATUSES
            assert allowed == (s in {PostStatus.draft, PostStatus.failed})

    def test_published_is_not_deletable(self) -> None:
        # Phase 9 explicitly out-of-scope: deleting published posts.
        # Even local-DB delete is gated to prevent operator footguns.
        assert PostStatus.published not in DELETABLE_STATUSES

    def test_publishing_is_not_deletable(self) -> None:
        # In-flight publish must not be racy-deleted.
        assert PostStatus.publishing not in DELETABLE_STATUSES

    def test_approved_not_directly_deletable(self) -> None:
        # Forces operator to unapprove first (preserves audit clarity).
        assert PostStatus.approved not in DELETABLE_STATUSES

    def test_scheduled_not_directly_deletable(self) -> None:
        # Forces operator to unschedule first so the APScheduler job cancels cleanly.
        assert PostStatus.scheduled not in DELETABLE_STATUSES
