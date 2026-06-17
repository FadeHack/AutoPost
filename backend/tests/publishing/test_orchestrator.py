"""Phase 11 Chunk A — tests for the platform-agnostic publish orchestrator.

Replaces the pre-Phase-11 publisher tests. The orchestrator owns status
flips, retry classification, char-limit gating, and aggregating per-target
outcomes back up to posts.status. Platform-specific HTTP is stubbed via a
fake Publisher registered for `Platform.linkedin`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.base import (
    Platform,
    PostCategory,
    PostStatus,
    TargetStatus,
)
from app.publishing import orchestrator
from app.publishing.base import (
    AuthPublishError,
    PermanentPublishError,
    PublishResult,
    Publisher,
    TransientPublishError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_post(
    *,
    status=PostStatus.scheduled,
    category=PostCategory.founder_insight,
    hook="A sharp hook",
    body="The body line one.\nLine two.",
    tags=("ai", "founders"),
):
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        category=category,
        hook=hook,
        body=body,
        tags=list(tags),
        linkedin_urn=None,
        published_at=None,
        error=None,
    )


def _fake_target(*, platform=Platform.linkedin, status=TargetStatus.pending, post=None, commentary=None):
    return SimpleNamespace(
        id=uuid4(),
        post_id=post.id if post else uuid4(),
        platform=platform,
        status=status,
        scheduled_at=None,
        published_at=None,
        external_urn=None,
        error=None,
        raw_request=None,
        commentary=commentary,
    )


def _make_session(*, target, post, other_targets=()):
    """AsyncMock session with `get` routing PostTarget → target, Post → post.
    `execute` returns `other_targets` for the aggregation query."""
    session = MagicMock()

    async def fake_get(model, _id):
        from app.models import Post, PostTarget

        if model is PostTarget:
            return target
        if model is Post:
            return post
        return None

    session.get = AsyncMock(side_effect=fake_get)

    async def fake_execute(_stmt):
        # All execute() calls in orchestrator return scalars().all() shaped
        # results. We don't differentiate which call this is — every test
        # that needs different shapes monkeypatches the helpers above.
        result = MagicMock()
        result.scalars.return_value.all.return_value = [target, *other_targets]
        return result

    session.execute = AsyncMock(side_effect=fake_execute)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    return session


class _FakePublisher(Publisher):
    """Stand-in for LinkedInPublisher; lets each test inject a `_callback`
    that returns a PublishResult or raises a PublishError."""

    platform = Platform.linkedin
    char_limit = 3000
    max_images = 20

    _callback = None

    async def publish(self, **_):  # type: ignore[override]
        cb = type(self)._callback
        if cb is None:
            return PublishResult(
                external_urn="urn:li:share:DEFAULT",
                raw_request={"text": "x"},
            )
        return cb()


@pytest.fixture
def patched(monkeypatch):
    """Stub registry → FakePublisher, account loader, asset selector, sleep."""
    # Reset callback per-test.
    _FakePublisher._callback = None
    monkeypatch.setattr(
        orchestrator,
        "get_publisher_class",
        lambda _platform: _FakePublisher,
    )
    monkeypatch.setattr(
        orchestrator,
        "_load_account",
        AsyncMock(return_value=SimpleNamespace(id=uuid4(), refresh_token=None)),
    )
    monkeypatch.setattr(
        orchestrator,
        "_select_publish_assets",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(orchestrator.asyncio, "sleep", AsyncMock())
    # Aggregation queries return only our target by default → terminal aggregation works.
    return _FakePublisher


# ---------------------------------------------------------------------------
# build_commentary
# ---------------------------------------------------------------------------


def test_build_commentary_includes_hook_body_and_tags():
    post = _fake_post(hook="Hot take.", body="Some body.", tags=["x", "y"])
    out = orchestrator.build_commentary(post)
    assert "Hot take." in out
    assert "Some body." in out
    assert "#x #y" in out


def test_build_commentary_no_escaping_at_orchestrator_layer():
    """Escaping is platform-specific (LinkedIn has reserved chars; Bluesky
    doesn't). The orchestrator hands off raw text and each publisher handles
    its own escape."""
    post = _fake_post(hook="(maybe)", body="hello @world", tags=[])
    out = orchestrator.build_commentary(post)
    assert "(maybe)" in out
    assert "@world" in out
    # No backslash-escaped chars from the orchestrator.
    assert "\\(" not in out and "\\@" not in out


def test_build_commentary_strips_duplicate_hook_from_legacy_body():
    post = _fake_post(
        hook="The hot take.",
        body="The hot take.\n\nReal body content.",
        tags=[],
    )
    out = orchestrator.build_commentary(post)
    assert out.count("The hot take.") == 1
    assert "Real body content." in out


def test_build_commentary_strips_trailing_hashtag_line_from_legacy_body():
    post = _fake_post(
        hook="Hook.",
        body="Real body.\n\n#ai #startups",
        tags=["ai", "startups"],
    )
    out = orchestrator.build_commentary(post)
    assert out.count("#ai") == 1
    assert out.endswith("#ai #startups")


# ---------------------------------------------------------------------------
# publish_target — happy paths
# ---------------------------------------------------------------------------


async def test_publish_target_happy_text_only(patched):
    post = _fake_post()
    target = _fake_target(post=post)
    session = _make_session(target=target, post=post)

    result = await orchestrator.publish_target(session, target.id)

    assert result.status == TargetStatus.published
    assert result.external_urn == "urn:li:share:DEFAULT"
    assert result.published_at is not None
    # Legacy compatibility: posts.linkedin_urn stamped from the first LinkedIn
    # target so any pre-Phase-11 reads keep working.
    assert post.linkedin_urn == "urn:li:share:DEFAULT"


async def test_publish_target_aggregates_post_status_when_all_targets_terminal(
    patched,
):
    post = _fake_post(status=PostStatus.scheduled)
    target = _fake_target(post=post)
    session = _make_session(target=target, post=post)

    await orchestrator.publish_target(session, target.id)

    # Only one target on the post, it published → posts.status should be aggregated.
    assert post.status == PostStatus.published
    assert post.published_at is not None


async def test_publish_target_leaves_post_status_alone_while_other_targets_pending(
    patched,
):
    post = _fake_post(status=PostStatus.scheduled)
    target = _fake_target(post=post)
    other_pending = _fake_target(post=post, platform=Platform.bluesky)
    session = _make_session(target=target, post=post, other_targets=[other_pending])

    await orchestrator.publish_target(session, target.id)

    # The Bluesky sibling is still pending → posts.status stays at scheduled.
    assert post.status == PostStatus.scheduled


# ---------------------------------------------------------------------------
# publish_target — error paths
# ---------------------------------------------------------------------------


async def test_publish_target_missing_raises(patched):
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(PermanentPublishError, match="not found"):
        await orchestrator.publish_target(session, uuid4())


async def test_publish_target_wrong_status_raises(patched):
    post = _fake_post()
    target = _fake_target(post=post, status=TargetStatus.published)
    session = _make_session(target=target, post=post)
    with pytest.raises(PermanentPublishError, match="cannot publish"):
        await orchestrator.publish_target(session, target.id)


async def test_publish_target_char_limit_exceeded_marks_failed(patched):
    post = _fake_post(body="x" * 10_000)  # well over 3000-char LinkedIn cap.
    target = _fake_target(post=post)
    session = _make_session(target=target, post=post)

    result = await orchestrator.publish_target(session, target.id)

    assert result.status == TargetStatus.failed
    assert "exceeds" in (result.error or "")


async def test_publish_target_permanent_error_marks_failed_no_retry(patched):
    call_count = {"n": 0}

    def _cb():
        call_count["n"] += 1
        raise PermanentPublishError("422: bad")

    _FakePublisher._callback = _cb
    post = _fake_post()
    target = _fake_target(post=post)
    session = _make_session(target=target, post=post)

    result = await orchestrator.publish_target(session, target.id)

    assert result.status == TargetStatus.failed
    assert call_count["n"] == 1


async def test_publish_target_transient_then_success(patched):
    call_count = {"n": 0}

    def _cb():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise TransientPublishError("429")
        return PublishResult(
            external_urn="urn:li:share:OK", raw_request={"text": "x"}
        )

    _FakePublisher._callback = _cb
    post = _fake_post()
    target = _fake_target(post=post)
    session = _make_session(target=target, post=post)

    result = await orchestrator.publish_target(session, target.id)

    assert result.status == TargetStatus.published
    assert result.external_urn == "urn:li:share:OK"
    assert call_count["n"] == 2


async def test_publish_target_transient_exhausts_attempts_then_fails(patched):
    call_count = {"n": 0}

    def _cb():
        call_count["n"] += 1
        raise TransientPublishError("503")

    _FakePublisher._callback = _cb
    post = _fake_post()
    target = _fake_target(post=post)
    session = _make_session(target=target, post=post)

    result = await orchestrator.publish_target(session, target.id)

    assert result.status == TargetStatus.failed
    assert call_count["n"] == orchestrator.MAX_ATTEMPTS


async def test_publish_target_auth_error_forces_refresh_then_succeeds(patched):
    call_count = {"n": 0}

    def _cb():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise AuthPublishError("401")
        return PublishResult(
            external_urn="urn:li:share:AFTER", raw_request={"text": "x"}
        )

    _FakePublisher._callback = _cb
    # Account with refresh_token so the auth retry path engages.
    account = SimpleNamespace(
        id=uuid4(),
        refresh_token="cipher",
        access_token="cipher",
        expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=1),
    )
    orchestrator._load_account = AsyncMock(return_value=account)  # type: ignore[assignment]

    post = _fake_post()
    target = _fake_target(post=post)
    session = _make_session(target=target, post=post)

    result = await orchestrator.publish_target(session, target.id)

    assert result.status == TargetStatus.published
    assert result.external_urn == "urn:li:share:AFTER"
    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# Phase 11 Chunk E — multi-platform fan-out (code-level E2E)
# ---------------------------------------------------------------------------


async def test_fan_out_persists_distinct_urns_per_platform(monkeypatch):
    """One draft → LinkedIn + Bluesky targets → each publishes and persists its
    own external_urn. The code-level stand-in for the live multi-platform E2E:
    proves dispatch + per-target persistence are platform-independent."""

    class _PlatformPublisher(Publisher):
        platform = Platform.linkedin  # overridden per-instance below
        char_limit = 3000
        max_images = 20

        def __init__(self, urn):
            self._urn = urn

        async def publish(self, **_):  # type: ignore[override]
            return PublishResult(external_urn=self._urn, raw_request={"text": "x"})

    urns = {
        Platform.linkedin: "urn:li:share:LI",
        Platform.bluesky: "at://did:plc:x/app.bsky.feed.post/BSKY",
    }
    # The orchestrator does `get_publisher_class(platform)()`, so return a
    # zero-arg factory that closes over the right per-platform urn.
    monkeypatch.setattr(
        orchestrator,
        "get_publisher_class",
        lambda platform: (lambda: _PlatformPublisher(urns[platform])),
    )
    monkeypatch.setattr(
        orchestrator,
        "_load_account",
        AsyncMock(return_value=SimpleNamespace(id=uuid4(), refresh_token=None)),
    )
    monkeypatch.setattr(
        orchestrator, "_select_publish_assets", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(orchestrator.asyncio, "sleep", AsyncMock())

    post = _fake_post()
    li_target = _fake_target(post=post, platform=Platform.linkedin)
    bsky_target = _fake_target(
        post=post, platform=Platform.bluesky, commentary="short bsky variant"
    )

    li_result = await orchestrator.publish_target(
        _make_session(target=li_target, post=post, other_targets=[bsky_target]),
        li_target.id,
    )
    bsky_result = await orchestrator.publish_target(
        _make_session(target=bsky_target, post=post, other_targets=[li_target]),
        bsky_target.id,
    )

    assert li_result.status == TargetStatus.published
    assert li_result.external_urn == "urn:li:share:LI"
    assert bsky_result.status == TargetStatus.published
    assert bsky_result.external_urn.endswith("/BSKY")
    # Distinct URNs persisted per platform — no cross-contamination.
    assert li_result.external_urn != bsky_result.external_urn
