"""Tests for the publisher orchestration.

No real DB, no real LinkedIn, no real Supabase. Pure-logic helpers tested directly;
the orchestrator is exercised with `AsyncMock` sessions + monkeypatched HTTP layer.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.base import AccountKind, PostCategory, PostStatus
from app.publishing import linkedin_client as lc
from app.publishing import publisher


# ---- Helpers ----------------------------------------------------------------


def _fake_post(
    *,
    status=PostStatus.approved,
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
        raw_request=None,
    )


def _fake_account(*, stale=False):
    expires_at = datetime.now(tz=timezone.utc) + (
        timedelta(minutes=1) if stale else timedelta(hours=2)
    )
    return SimpleNamespace(
        id=uuid4(),
        account_kind=AccountKind.personal,
        member_sub="abc-sub",
        org_urn=None,
        access_token="encrypted_access",
        refresh_token="encrypted_refresh",
        expires_at=expires_at,
    )


def _make_session():
    """AsyncMock session with the methods publisher uses."""
    session = MagicMock()
    session.get = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()  # sync — SQLAlchemy session.add is sync
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


# ---- _build_commentary -----------------------------------------------------


def test_build_commentary_includes_hook_body_and_tags():
    post = _fake_post(hook="Hot take.", body="Some body.", tags=["x", "y"])
    out = publisher._build_commentary(post)
    assert "Hot take." in out
    assert "Some body." in out
    assert "#x #y" in out


def test_build_commentary_escapes_reserved_chars():
    post = _fake_post(hook="(maybe)", body="hello @world", tags=[])
    out = publisher._build_commentary(post)
    assert "\\(" in out and "\\)" in out
    assert "\\@" in out


def test_build_commentary_no_tags_no_trailing_blank():
    post = _fake_post(tags=[])
    out = publisher._build_commentary(post)
    assert not out.endswith("\n")
    assert "#" not in out


def test_build_commentary_strips_duplicate_hook_from_legacy_body():
    # Legacy drafts: Stage 3 used to put the hook at the start of body.
    # Publisher must defend so the live post doesn't show the hook twice.
    post = _fake_post(
        hook="The hot take.",
        body="The hot take.\n\nReal body content.",
        tags=[],
    )
    out = publisher._build_commentary(post)
    # Hook appears exactly once.
    assert out.count("The hot take.") == 1
    assert "Real body content." in out


def test_build_commentary_strips_trailing_hashtag_line_from_legacy_body():
    post = _fake_post(
        hook="Hook.",
        body="Real body.\n\n#ai #startups",
        tags=["ai", "startups"],
    )
    out = publisher._build_commentary(post)
    # Tags appear once at the end via the tag_line, not twice from body.
    assert out.count("#ai") == 1
    assert out.count("#startups") == 1
    assert out.endswith("#ai #startups")


# ---- _classify --------------------------------------------------------------


@pytest.mark.parametrize("status_code", [401, 403])
def test_classify_auth(status_code):
    err = lc.LinkedInAPIError("nope", status=status_code, body="")
    assert publisher._classify(err) == "auth"


@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
def test_classify_transient(status_code):
    err = lc.LinkedInAPIError("nope", status=status_code, body="")
    assert publisher._classify(err) == "transient"


@pytest.mark.parametrize("status_code", [400, 404, 422])
def test_classify_permanent(status_code):
    err = lc.LinkedInAPIError("nope", status=status_code, body="")
    assert publisher._classify(err) == "permanent"


# ---- _account_author_urn ----------------------------------------------------


def test_account_author_urn_personal():
    acc = _fake_account()
    assert publisher._account_author_urn(acc) == "urn:li:person:abc-sub"


# ---- ensure_fresh_token -----------------------------------------------------


async def test_ensure_fresh_token_returns_decrypted_when_fresh(monkeypatch):
    acc = _fake_account(stale=False)
    monkeypatch.setattr(publisher, "decrypt", lambda s: f"DEC({s})")
    session = _make_session()
    tok = await publisher.ensure_fresh_token(session, acc)
    assert tok == "DEC(encrypted_access)"
    # No refresh attempted
    session.flush.assert_not_called()


async def test_ensure_fresh_token_refreshes_when_stale(monkeypatch):
    acc = _fake_account(stale=True)
    monkeypatch.setattr(publisher, "decrypt", lambda s: f"DEC({s})")
    monkeypatch.setattr(publisher, "encrypt", lambda s: f"ENC({s})")

    new_expires = datetime.now(tz=timezone.utc) + timedelta(hours=24)
    fake_response = SimpleNamespace(
        access_token="newAccess",
        refresh_token="newRefresh",
        expires_at=new_expires,
    )
    monkeypatch.setattr(
        publisher.lc, "refresh_access_token", AsyncMock(return_value=fake_response)
    )

    session = _make_session()
    tok = await publisher.ensure_fresh_token(session, acc)

    assert tok == "newAccess"
    assert acc.access_token == "ENC(newAccess)"
    assert acc.refresh_token == "ENC(newRefresh)"
    assert acc.expires_at == new_expires
    session.flush.assert_awaited_once()


# ---- publish_post — orchestration -------------------------------------------


@pytest.fixture
def patched_publish(monkeypatch):
    """Wire up the common monkeypatches for publish_post tests.

    Returns a dict of the mocks so each test can tune behavior.
    """
    monkeypatch.setattr(publisher, "decrypt", lambda s: f"DEC({s})")
    monkeypatch.setattr(publisher, "encrypt", lambda s: f"ENC({s})")
    monkeypatch.setattr(publisher.storage, "public_url", lambda p: f"https://cdn/{p}")

    # No assets by default → text-only post
    select_assets = AsyncMock(return_value=[])
    load_account = AsyncMock(return_value=_fake_account())
    download_png = AsyncMock(return_value=b"PNG")
    upload_image = AsyncMock(return_value="urn:li:image:UPLOADED")
    create_post = AsyncMock(return_value="urn:li:share:1234")
    refresh = AsyncMock()

    upload_document = AsyncMock(return_value="urn:li:document:UPLOADED")
    build_pdf = AsyncMock(return_value=b"PDFBYTES")

    monkeypatch.setattr(publisher, "_select_publish_assets", select_assets)
    monkeypatch.setattr(publisher, "_load_personal_account", load_account)
    monkeypatch.setattr(publisher, "_download_png", download_png)
    monkeypatch.setattr(publisher.lc, "upload_image", upload_image)
    monkeypatch.setattr(publisher.lc, "upload_document", upload_document)
    monkeypatch.setattr(publisher.lc, "create_post", create_post)
    monkeypatch.setattr(publisher.lc, "refresh_access_token", refresh)
    monkeypatch.setattr(publisher.pdf_assembler, "build_pdf", build_pdf)
    # Always-fresh tokens
    monkeypatch.setattr(publisher.lc, "_is_token_stale", lambda _: False)
    # Don't actually sleep on backoff
    monkeypatch.setattr(publisher.asyncio, "sleep", AsyncMock())

    return {
        "select_assets": select_assets,
        "load_account": load_account,
        "download_png": download_png,
        "upload_image": upload_image,
        "upload_document": upload_document,
        "build_pdf": build_pdf,
        "create_post": create_post,
        "refresh": refresh,
    }


async def test_publish_post_text_only_happy(patched_publish):
    post = _fake_post()
    session = _make_session()
    session.get = AsyncMock(return_value=post)

    result = await publisher.publish_post(session, post.id)

    assert result.status == PostStatus.published
    assert result.linkedin_urn == "urn:li:share:1234"
    assert result.published_at is not None
    # text-only: no image upload calls
    patched_publish["upload_image"].assert_not_called()
    patched_publish["create_post"].assert_awaited_once()


async def test_publish_post_single_image_happy(patched_publish):
    asset = SimpleNamespace(
        id=uuid4(),
        image_path="post/asset.png",
        linkedin_asset_urn=None,
        template_id=uuid4(),
    )
    patched_publish["select_assets"].return_value = [asset]

    post = _fake_post()
    session = _make_session()
    session.get = AsyncMock(return_value=post)

    result = await publisher.publish_post(session, post.id)

    assert result.status == PostStatus.published
    patched_publish["upload_image"].assert_awaited_once()
    assert asset.linkedin_asset_urn == "urn:li:image:UPLOADED"


async def test_publish_post_multi_slide_uploads_document(patched_publish):
    """Multi-slide carousels go through the LinkedIn Documents API (PDF)
    instead of MultiImage, so the live post is a native swipeable carousel."""
    assets = [
        SimpleNamespace(
            id=uuid4(),
            image_path=f"post/asset{i}.png",
            linkedin_asset_urn=None,
            template_id=uuid4(),
        )
        for i in range(3)
    ]
    patched_publish["select_assets"].return_value = assets

    post = _fake_post(category=PostCategory.carousel)
    session = _make_session()
    session.get = AsyncMock(return_value=post)

    result = await publisher.publish_post(session, post.id)

    assert result.status == PostStatus.published
    # Slides aren't uploaded as images; they become a single PDF document.
    patched_publish["upload_image"].assert_not_called()
    patched_publish["build_pdf"].assert_awaited_once()
    patched_publish["upload_document"].assert_awaited_once()
    # All three slide PNGs were downloaded and handed to the PDF builder.
    assert patched_publish["download_png"].await_count == 3
    # Every asset row gets stamped with the same document URN for traceability.
    for a in assets:
        assert a.linkedin_asset_urn == "urn:li:document:UPLOADED"


async def test_publish_post_wrong_status_raises(patched_publish):
    post = _fake_post(status=PostStatus.draft)
    session = _make_session()
    session.get = AsyncMock(return_value=post)

    with pytest.raises(publisher.PermanentPublishError, match="cannot publish"):
        await publisher.publish_post(session, post.id)


async def test_publish_post_missing_raises(patched_publish):
    session = _make_session()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(publisher.PermanentPublishError, match="not found"):
        await publisher.publish_post(session, uuid4())


async def test_publish_post_permanent_4xx_marks_failed(patched_publish):
    patched_publish["create_post"].side_effect = lc.LinkedInAPIError(
        "bad payload", status=422, body="UNPROCESSABLE"
    )
    post = _fake_post()
    session = _make_session()
    session.get = AsyncMock(return_value=post)

    result = await publisher.publish_post(session, post.id)

    assert result.status == PostStatus.failed
    assert "422" in (result.error or "")
    # Permanent → single attempt
    assert patched_publish["create_post"].await_count == 1


async def test_publish_post_transient_then_success(patched_publish):
    patched_publish["create_post"].side_effect = [
        lc.LinkedInAPIError("rate", status=429, body=""),
        "urn:li:share:OK",
    ]
    post = _fake_post()
    session = _make_session()
    session.get = AsyncMock(return_value=post)

    result = await publisher.publish_post(session, post.id)

    assert result.status == PostStatus.published
    assert result.linkedin_urn == "urn:li:share:OK"
    assert patched_publish["create_post"].await_count == 2


async def test_publish_post_transient_exhausts_attempts_then_fails(patched_publish):
    patched_publish["create_post"].side_effect = lc.LinkedInAPIError(
        "boom", status=503, body=""
    )
    post = _fake_post()
    session = _make_session()
    session.get = AsyncMock(return_value=post)

    result = await publisher.publish_post(session, post.id)

    assert result.status == PostStatus.failed
    assert patched_publish["create_post"].await_count == publisher.MAX_ATTEMPTS


async def test_publish_post_auth_error_forces_refresh_then_succeeds(
    patched_publish, monkeypatch
):
    patched_publish["create_post"].side_effect = [
        lc.LinkedInAPIError("denied", status=401, body=""),
        "urn:li:share:AFTER",
    ]
    post = _fake_post()
    session = _make_session()
    session.get = AsyncMock(return_value=post)

    # ensure_fresh_token tracking — patch through real fn but mock refresh
    new_expires = datetime.now(tz=timezone.utc) + timedelta(hours=24)
    patched_publish["refresh"].return_value = SimpleNamespace(
        access_token="A2", refresh_token="R2", expires_at=new_expires
    )
    # Force "stale" check to True on second call so refresh kicks in
    is_stale_calls = {"n": 0}

    def fake_stale(exp):
        is_stale_calls["n"] += 1
        # First call (pre-attempt 1): fresh. After 401, publisher sets
        # expires_at = now, so subsequent ensure_fresh_token must see stale.
        return is_stale_calls["n"] > 1

    monkeypatch.setattr(publisher.lc, "_is_token_stale", fake_stale)

    result = await publisher.publish_post(session, post.id)

    assert result.status == PostStatus.published
    assert result.linkedin_urn == "urn:li:share:AFTER"
    patched_publish["refresh"].assert_awaited_once()
