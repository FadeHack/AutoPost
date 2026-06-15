"""LinkedIn-specific publisher unit tests.

Covers the helpers that moved from the old `publisher.py` into
`publishing/linkedin.py` — token refresh, author URN, HTTP error
classification, and the publish path with image/document upload mocked.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.base import AccountKind
from app.publishing import linkedin as lkdn
from app.publishing import linkedin_client as lc
from app.publishing.base import (
    AuthPublishError,
    PermanentPublishError,
    TransientPublishError,
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


# ---------------------------------------------------------------------------
# _account_author_urn
# ---------------------------------------------------------------------------


def test_account_author_urn_personal():
    acc = _fake_account()
    assert lkdn._account_author_urn(acc) == "urn:li:person:abc-sub"


# ---------------------------------------------------------------------------
# _classify_to_publish_error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [401, 403])
def test_classify_auth(status_code):
    err = lc.LinkedInAPIError("nope", status=status_code, body="")
    out = lkdn._classify_to_publish_error(err)
    assert isinstance(out, AuthPublishError)


@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
def test_classify_transient(status_code):
    err = lc.LinkedInAPIError("nope", status=status_code, body="")
    out = lkdn._classify_to_publish_error(err)
    assert isinstance(out, TransientPublishError)


@pytest.mark.parametrize("status_code", [400, 404, 422])
def test_classify_permanent(status_code):
    err = lc.LinkedInAPIError("nope", status=status_code, body="")
    out = lkdn._classify_to_publish_error(err)
    assert isinstance(out, PermanentPublishError)


# ---------------------------------------------------------------------------
# _ensure_fresh_token
# ---------------------------------------------------------------------------


async def test_ensure_fresh_token_returns_decrypted_when_fresh(monkeypatch):
    acc = _fake_account(stale=False)
    monkeypatch.setattr(lkdn, "decrypt", lambda s: f"DEC({s})")
    session = SimpleNamespace(flush=AsyncMock())
    tok = await lkdn._ensure_fresh_token(session, acc)
    assert tok == "DEC(encrypted_access)"
    session.flush.assert_not_called()


async def test_ensure_fresh_token_refreshes_when_stale(monkeypatch):
    acc = _fake_account(stale=True)
    monkeypatch.setattr(lkdn, "decrypt", lambda s: f"DEC({s})")
    monkeypatch.setattr(lkdn, "encrypt", lambda s: f"ENC({s})")

    new_expires = datetime.now(tz=timezone.utc) + timedelta(hours=24)
    fake_response = SimpleNamespace(
        access_token="newAccess",
        refresh_token="newRefresh",
        expires_at=new_expires,
    )
    monkeypatch.setattr(
        lkdn.lc, "refresh_access_token", AsyncMock(return_value=fake_response)
    )

    session = SimpleNamespace(flush=AsyncMock())
    tok = await lkdn._ensure_fresh_token(session, acc)

    assert tok == "newAccess"
    assert acc.access_token == "ENC(newAccess)"
    assert acc.refresh_token == "ENC(newRefresh)"
    assert acc.expires_at == new_expires
    session.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# LinkedInPublisher.publish — text / image / multi-slide
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_publish(monkeypatch):
    """Stub HTTP + storage so publish() is exercised without network."""
    monkeypatch.setattr(lkdn, "decrypt", lambda s: f"DEC({s})")
    monkeypatch.setattr(lkdn, "encrypt", lambda s: f"ENC({s})")
    monkeypatch.setattr(lkdn.storage, "public_url", lambda p: f"https://cdn/{p}")
    monkeypatch.setattr(lkdn, "_download_png", AsyncMock(return_value=b"PNG"))
    monkeypatch.setattr(
        lkdn.lc, "upload_image", AsyncMock(return_value="urn:li:image:UPLOADED")
    )
    monkeypatch.setattr(
        lkdn.lc, "upload_document",
        AsyncMock(return_value="urn:li:document:UPLOADED"),
    )
    create_post = AsyncMock(return_value="urn:li:share:1234")
    monkeypatch.setattr(lkdn.lc, "create_post", create_post)
    monkeypatch.setattr(lkdn.pdf_assembler, "build_pdf", AsyncMock(return_value=b"PDFBYTES"))
    monkeypatch.setattr(lkdn.lc, "_is_token_stale", lambda _: False)
    return {"create_post": create_post}


async def test_linkedin_publish_text_only(patched_publish):
    publisher = lkdn.LinkedInPublisher()
    post = SimpleNamespace(hook="Hook.", body="Body.", tags=["x"])
    account = _fake_account()
    session = SimpleNamespace(flush=AsyncMock())

    result = await publisher.publish(
        session=session,
        post=post,
        account=account,
        commentary="Hook.\n\nBody.\n\n#x",
        assets=[],
    )

    assert result.external_urn == "urn:li:share:1234"
    patched_publish["create_post"].assert_awaited_once()


async def test_linkedin_publish_single_image(patched_publish):
    publisher = lkdn.LinkedInPublisher()
    asset = SimpleNamespace(
        id=uuid4(), image_path="post/a.png", linkedin_asset_urn=None, template_id=uuid4()
    )
    post = SimpleNamespace(hook="Hook.", body="Body.", tags=[])
    account = _fake_account()
    session = SimpleNamespace(flush=AsyncMock())

    result = await publisher.publish(
        session=session,
        post=post,
        account=account,
        commentary="Hook.\n\nBody.",
        assets=[asset],
    )

    assert result.external_urn == "urn:li:share:1234"
    assert asset.linkedin_asset_urn == "urn:li:image:UPLOADED"


async def test_linkedin_publish_multi_slide_uploads_document(patched_publish):
    publisher = lkdn.LinkedInPublisher()
    assets = [
        SimpleNamespace(
            id=uuid4(), image_path=f"post/a{i}.png",
            linkedin_asset_urn=None, template_id=uuid4(),
        )
        for i in range(3)
    ]
    post = SimpleNamespace(hook="H.", body="B.", tags=[])
    account = _fake_account()
    session = SimpleNamespace(flush=AsyncMock())

    result = await publisher.publish(
        session=session,
        post=post,
        account=account,
        commentary="H.\n\nB.",
        assets=assets,
    )

    assert result.external_urn == "urn:li:share:1234"
    for a in assets:
        assert a.linkedin_asset_urn == "urn:li:document:UPLOADED"


async def test_linkedin_publish_translates_linkedin_api_errors(patched_publish):
    publisher = lkdn.LinkedInPublisher()
    patched_publish["create_post"].side_effect = lc.LinkedInAPIError(
        "bad", status=422, body="x"
    )
    post = SimpleNamespace(hook="H.", body="B.", tags=[])
    account = _fake_account()
    session = SimpleNamespace(flush=AsyncMock())

    with pytest.raises(PermanentPublishError):
        await publisher.publish(
            session=session,
            post=post,
            account=account,
            commentary="text",
            assets=[],
        )
