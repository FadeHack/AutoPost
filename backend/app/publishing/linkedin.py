"""LinkedInPublisher — refactored from the pre-Phase-11 `publisher.py` into the
Publisher ABC shape. HTTP surface lives in `linkedin_client.py` (unchanged);
token refresh + author URN resolution moved here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt, encrypt
from app.models import GeneratedAsset, LinkedInAccount, Post
from app.models.base import Platform
from app.publishing import linkedin_client as lc
from app.publishing.base import (
    AuthPublishError,
    PermanentPublishError,
    PublishResult,
    Publisher,
    TransientPublishError,
    register,
)
from app.rendering import pdf as pdf_assembler
from app.rendering import storage

log = structlog.get_logger()


async def _ensure_fresh_token(
    session: AsyncSession, account: LinkedInAccount
) -> str:
    """Return a usable plaintext access token. Refreshes + re-encrypts in
    place if the stored one is within `TOKEN_REFRESH_LEAD` of expiry."""
    if not lc._is_token_stale(account.expires_at) or not account.refresh_token:
        return decrypt(account.access_token)

    refresh_plain = decrypt(account.refresh_token)
    log.info("linkedin.token.refreshing", account_id=str(account.id))
    new_tokens = await lc.refresh_access_token(refresh_plain)

    account.access_token = encrypt(new_tokens.access_token)
    if new_tokens.refresh_token and new_tokens.refresh_token != refresh_plain:
        account.refresh_token = encrypt(new_tokens.refresh_token)
    account.expires_at = new_tokens.expires_at
    await session.flush()
    log.info(
        "linkedin.token.refreshed",
        account_id=str(account.id),
        expires_at=account.expires_at.isoformat(),
    )
    return new_tokens.access_token


def _account_author_urn(account: LinkedInAccount) -> str:
    kind = account.account_kind.value if hasattr(account.account_kind, "value") else str(account.account_kind)
    return lc.author_urn(kind, member_sub=account.member_sub, org_urn=account.org_urn)


async def _download_png(public_url: str) -> bytes:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        r = await client.get(public_url)
    if r.status_code != 200:
        raise PermanentPublishError(
            f"asset download failed: {r.status_code} {public_url}"
        )
    return r.content


def _classify_to_publish_error(err: lc.LinkedInAPIError) -> Exception:
    """Map LinkedIn HTTP error onto the abstract PublishError taxonomy."""
    if err.status in (401, 403):
        return AuthPublishError(f"{err.status}: {err}")
    if err.status == 429 or 500 <= err.status < 600:
        return TransientPublishError(f"{err.status}: {err}")
    return PermanentPublishError(f"{err.status}: {err}")


@register
class LinkedInPublisher(Publisher):
    platform = Platform.linkedin
    # LinkedIn allows ~3000 chars; we cap looser than reality since the founder-
    # voice prompt produces 140-220 words ≈ 1100-1600 chars and we want the gate
    # to surface only on legitimate edge cases (legacy long-form drafts).
    char_limit = 3000
    max_images = 20
    supports_documents = True

    async def publish(
        self,
        *,
        session: AsyncSession,
        post: Post,
        account: LinkedInAccount,
        commentary: str,
        assets: list[GeneratedAsset],
    ) -> PublishResult:
        access_token = await _ensure_fresh_token(session, account)
        author = _account_author_urn(account)
        # Compose escaped commentary at the last possible moment so the
        # orchestrator sees raw text and only LinkedIn-specific code knows
        # about its little-text reserved chars.
        escaped = lc.escape_commentary(commentary)

        try:
            if not assets:
                payload = lc.build_text_post_payload(
                    author=author, commentary=escaped
                )
            elif len(assets) == 1:
                a = assets[0]
                png = await _download_png(storage.public_url(a.image_path))
                image_urn = await lc.upload_image(
                    access_token, owner_urn=author, png_bytes=png
                )
                a.linkedin_asset_urn = image_urn
                payload = lc.build_image_post_payload(
                    author=author, commentary=escaped, image_urn=image_urn
                )
            else:
                # Multi-slide → LinkedIn document carousel (swipeable PDF).
                pngs = [
                    await _download_png(storage.public_url(a.image_path))
                    for a in assets
                ]
                pdf_bytes = await pdf_assembler.build_pdf(pngs)
                document_urn = await lc.upload_document(
                    access_token, owner_urn=author, pdf_bytes=pdf_bytes
                )
                for a in assets:
                    a.linkedin_asset_urn = document_urn
                payload = lc.build_document_post_payload(
                    author=author,
                    commentary=escaped,
                    document_urn=document_urn,
                    title="carousel.pdf",
                )

            urn = await lc.create_post(access_token, payload)
            return PublishResult(external_urn=urn, raw_request=payload)
        except lc.LinkedInAPIError as e:
            raise _classify_to_publish_error(e) from e


# --- Account loader (used by orchestrator) ---


async def load_account(
    session: AsyncSession, post: Post  # noqa: ARG001 — kept for parity w/ other loaders
) -> LinkedInAccount:
    """MVP: single-user, single connected personal account."""
    from sqlalchemy import select

    from app.models.base import AccountKind

    stmt = (
        select(LinkedInAccount)
        .where(LinkedInAccount.account_kind == AccountKind.personal)
        .order_by(LinkedInAccount.created_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        raise PermanentPublishError("no connected LinkedIn personal account")
    return row
