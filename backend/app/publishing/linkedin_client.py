"""LinkedIn /rest API client — image upload + Posts API + token refresh.

Pure HTTP surface (no DB). The publisher (`publisher.py`) layers DB orchestration
on top: load Post + GeneratedAssets, decrypt token, call into here, persist URN.

Endpoints used (LinkedIn-Version pinned via `settings.LINKEDIN_API_VERSION`):
- POST /rest/images?action=initializeUpload  → returns uploadUrl + image URN
- PUT  {uploadUrl}                            → upload PNG binary
- POST /rest/posts                            → publish (text / image / multiImage)

Docs verified against learn.microsoft.com/en-us/linkedin/marketing 2026-05 view.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
import structlog

from app.config import settings
from app.publishing import oauth

log = structlog.get_logger()

LINKEDIN_API_BASE = "https://api.linkedin.com"
INITIALIZE_UPLOAD_URL = f"{LINKEDIN_API_BASE}/rest/images?action=initializeUpload"
INITIALIZE_DOCUMENT_UPLOAD_URL = (
    f"{LINKEDIN_API_BASE}/rest/documents?action=initializeUpload"
)
DOCUMENTS_URL = f"{LINKEDIN_API_BASE}/rest/documents"
POSTS_URL = f"{LINKEDIN_API_BASE}/rest/posts"

# Documents are processed async by LinkedIn (WAITING_UPLOAD → PROCESSING → AVAILABLE).
# Poll until AVAILABLE before creating the post.
DOCUMENT_POLL_INTERVAL_S = 2.0
DOCUMENT_POLL_TIMEOUT_S = 90.0

# How long before token expiry we proactively refresh. LinkedIn access tokens
# live ~60 days; 5 min lead is plenty and avoids racing the wall clock.
TOKEN_REFRESH_LEAD = timedelta(minutes=5)

# Per-request total timeout. Image uploads can be slow on cold buckets; LinkedIn's
# DMS-uploads endpoint occasionally takes 5-10s for a 200KB PNG.
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class LinkedInAPIError(Exception):
    """Raised when LinkedIn returns a non-success status. `status` and `body` carried
    through so the publisher can log + categorize retryable vs permanent failures."""

    def __init__(self, message: str, *, status: int, body: str):
        super().__init__(message)
        self.status = status
        self.body = body


# --- Headers ---


def _post_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": settings.LINKEDIN_API_VERSION,
        "Content-Type": "application/json",
    }


def _image_init_headers(access_token: str) -> dict[str, str]:
    # Same as post but kept separate so future tweaks (extra X-RestLi-Method etc.)
    # don't leak across endpoint families.
    return _post_headers(access_token)


# --- Commentary escaping (LinkedIn "little text format") ---

# Per LinkedIn docs, these characters are reserved by the little-text-format parser
# and must be backslash-escaped in raw commentary text. Plain `#hashtag` works as-is —
# LinkedIn auto-converts it to the {hashtag|#|x} template on read.
_LITTLE_TEXT_RESERVED = "\\<>#~_*[](){}@|"


def escape_commentary(text: str) -> str:
    """Escape LinkedIn little-text reserved characters in plain commentary."""
    out = []
    for ch in text:
        if ch in _LITTLE_TEXT_RESERVED:
            out.append("\\")
        out.append(ch)
    return "".join(out)


# --- Author URN ---


def author_urn(account_kind: str, *, member_sub: str | None, org_urn: str | None) -> str:
    """Build the LinkedIn author URN per the account kind.

    `personal` → `urn:li:person:<member_sub>` (the OIDC `sub` claim)
    `organization` → `urn:li:organization:<org_urn>`
    """
    if account_kind == "personal":
        if not member_sub:
            raise ValueError("personal account missing member_sub")
        return f"urn:li:person:{member_sub}"
    if account_kind == "organization":
        if not org_urn:
            raise ValueError("organization account missing org_urn")
        return f"urn:li:organization:{org_urn}"
    raise ValueError(f"unknown account_kind: {account_kind}")


# --- Image upload ---


@dataclass(frozen=True)
class InitializeUploadResult:
    upload_url: str
    image_urn: str  # urn:li:image:XXX
    upload_url_expires_at: int  # ms epoch


async def initialize_image_upload(
    access_token: str, *, owner_urn: str
) -> InitializeUploadResult:
    """POST /rest/images?action=initializeUpload — register an upcoming upload.

    `owner_urn` must be the same person/organization URN we'll use as `author` on
    the eventual /rest/posts call. LinkedIn enforces ownership matching.
    """
    body = {"initializeUploadRequest": {"owner": owner_urn}}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(
            INITIALIZE_UPLOAD_URL, headers=_image_init_headers(access_token), json=body
        )
    if r.status_code != 200:
        raise LinkedInAPIError(
            f"initializeUpload failed: {r.status_code}",
            status=r.status_code,
            body=r.text,
        )
    value = r.json().get("value", {})
    try:
        return InitializeUploadResult(
            upload_url=value["uploadUrl"],
            image_urn=value["image"],
            upload_url_expires_at=int(value.get("uploadUrlExpiresAt", 0)),
        )
    except KeyError as e:
        raise LinkedInAPIError(
            f"initializeUpload response missing field: {e}",
            status=r.status_code,
            body=r.text,
        ) from e


async def upload_image_binary(upload_url: str, *, png_bytes: bytes) -> None:
    """PUT the raw PNG bytes to the uploadUrl returned by initialize_image_upload.

    The uploadUrl is short-lived and bears its own signed-auth in the query string,
    but LinkedIn still requires the bearer header on the PUT. Empty body on 201.
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.put(
            upload_url,
            content=png_bytes,
            headers={"Content-Type": "application/octet-stream"},
        )
    if r.status_code not in (200, 201):
        raise LinkedInAPIError(
            f"image upload failed: {r.status_code}",
            status=r.status_code,
            body=r.text,
        )


async def upload_image(
    access_token: str, *, owner_urn: str, png_bytes: bytes
) -> str:
    """High-level: register + upload + return the image URN ready for use in a post."""
    init = await initialize_image_upload(access_token, owner_urn=owner_urn)
    await upload_image_binary(init.upload_url, png_bytes=png_bytes)
    log.info(
        "linkedin.image.uploaded",
        image_urn=init.image_urn,
        bytes=len(png_bytes),
    )
    return init.image_urn


# --- Document upload (swipeable carousel = PDF document post) ---


@dataclass(frozen=True)
class InitializeDocumentUploadResult:
    upload_url: str
    document_urn: str  # urn:li:document:XXX
    upload_url_expires_at: int  # ms epoch


async def initialize_document_upload(
    access_token: str, *, owner_urn: str
) -> InitializeDocumentUploadResult:
    """POST /rest/documents?action=initializeUpload — register a PDF upload."""
    body = {"initializeUploadRequest": {"owner": owner_urn}}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(
            INITIALIZE_DOCUMENT_UPLOAD_URL,
            headers=_post_headers(access_token),
            json=body,
        )
    if r.status_code != 200:
        raise LinkedInAPIError(
            f"initializeDocumentUpload failed: {r.status_code}",
            status=r.status_code,
            body=r.text,
        )
    value = r.json().get("value", {})
    try:
        return InitializeDocumentUploadResult(
            upload_url=value["uploadUrl"],
            document_urn=value["document"],
            upload_url_expires_at=int(value.get("uploadUrlExpiresAt", 0)),
        )
    except KeyError as e:
        raise LinkedInAPIError(
            f"initializeDocumentUpload response missing field: {e}",
            status=r.status_code,
            body=r.text,
        ) from e


async def upload_document_binary(upload_url: str, *, pdf_bytes: bytes) -> None:
    """PUT the raw PDF bytes to the documents uploadUrl. 201 on success."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.put(
            upload_url,
            content=pdf_bytes,
            headers={"Content-Type": "application/octet-stream"},
        )
    if r.status_code not in (200, 201):
        raise LinkedInAPIError(
            f"document upload failed: {r.status_code}",
            status=r.status_code,
            body=r.text,
        )


async def get_document_status(access_token: str, *, document_urn: str) -> str:
    """GET /rest/documents/{urn} → status string.

    States: WAITING_UPLOAD, PROCESSING, AVAILABLE, PROCESSING_FAILED.
    """
    # LinkedIn's Rest.li requires URL-encoded URNs in path keys.
    encoded = quote(document_urn, safe="")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(
            f"{DOCUMENTS_URL}/{encoded}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "LinkedIn-Version": settings.LINKEDIN_API_VERSION,
                "X-Restli-Protocol-Version": "2.0.0",
            },
        )
    if r.status_code != 200:
        raise LinkedInAPIError(
            f"get_document failed: {r.status_code}",
            status=r.status_code,
            body=r.text,
        )
    return str(r.json().get("status") or "")


async def wait_for_document_available(
    access_token: str,
    *,
    document_urn: str,
    interval_s: float = DOCUMENT_POLL_INTERVAL_S,
    timeout_s: float = DOCUMENT_POLL_TIMEOUT_S,
) -> None:
    """Poll document status until AVAILABLE. Raises on PROCESSING_FAILED or timeout."""
    elapsed = 0.0
    while elapsed < timeout_s:
        status = await get_document_status(access_token, document_urn=document_urn)
        if status == "AVAILABLE":
            return
        if status == "PROCESSING_FAILED":
            raise LinkedInAPIError(
                f"document processing failed for {document_urn}",
                status=422,
                body=status,
            )
        await asyncio.sleep(interval_s)
        elapsed += interval_s
    raise LinkedInAPIError(
        f"document {document_urn} did not become AVAILABLE within {timeout_s}s",
        status=504,
        body="timeout",
    )


async def upload_document(
    access_token: str, *, owner_urn: str, pdf_bytes: bytes
) -> str:
    """High-level: init + upload + poll → return document URN ready for a post."""
    init = await initialize_document_upload(access_token, owner_urn=owner_urn)
    await upload_document_binary(init.upload_url, pdf_bytes=pdf_bytes)
    await wait_for_document_available(access_token, document_urn=init.document_urn)
    log.info(
        "linkedin.document.uploaded",
        document_urn=init.document_urn,
        bytes=len(pdf_bytes),
    )
    return init.document_urn


# --- Post creation ---


def _post_envelope(*, author: str, commentary: str) -> dict:
    """Fields common to every post type. Caller adds `content` if any."""
    return {
        "author": author,
        "commentary": commentary,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }


def build_text_post_payload(*, author: str, commentary: str) -> dict:
    return _post_envelope(author=author, commentary=commentary)


def build_image_post_payload(
    *, author: str, commentary: str, image_urn: str, alt_text: str | None = None
) -> dict:
    media: dict = {"id": image_urn}
    if alt_text:
        media["altText"] = alt_text
    payload = _post_envelope(author=author, commentary=commentary)
    payload["content"] = {"media": media}
    return payload


def build_multi_image_post_payload(
    *,
    author: str,
    commentary: str,
    images: list[tuple[str, str | None]],
) -> dict:
    """Carousel = LinkedIn MultiImage (organic, 2-20 images).

    `images` is a list of (image_urn, alt_text|None) tuples in display order.
    """
    if not (2 <= len(images) <= 20):
        raise ValueError(f"multiImage requires 2-20 images, got {len(images)}")
    image_entries: list[dict] = []
    for urn, alt in images:
        entry: dict = {"id": urn}
        if alt:
            entry["altText"] = alt
        image_entries.append(entry)
    payload = _post_envelope(author=author, commentary=commentary)
    payload["content"] = {"multiImage": {"images": image_entries}}
    return payload


def build_document_post_payload(
    *, author: str, commentary: str, document_urn: str, title: str
) -> dict:
    """Document post — the native swipeable LinkedIn carousel.

    `title` is the displayed document filename (e.g. "carousel.pdf") and is
    required by the API.
    """
    payload = _post_envelope(author=author, commentary=commentary)
    payload["content"] = {"media": {"id": document_urn, "title": title}}
    return payload


async def create_post(access_token: str, payload: dict) -> str:
    """POST /rest/posts → returns the new post URN (urn:li:share:X or urn:li:ugcPost:X).

    The URN is in the `x-restli-id` response header. 201 on success.
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(POSTS_URL, headers=_post_headers(access_token), json=payload)
    if r.status_code != 201:
        raise LinkedInAPIError(
            f"create_post failed: {r.status_code}",
            status=r.status_code,
            body=r.text,
        )
    urn = r.headers.get("x-restli-id") or r.headers.get("X-RestLi-Id")
    if not urn:
        raise LinkedInAPIError(
            "create_post succeeded but x-restli-id header missing",
            status=r.status_code,
            body=r.text,
        )
    log.info("linkedin.post.created", urn=urn)
    return urn


# --- Token refresh ---


def _is_token_stale(expires_at: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(tz=timezone.utc) + TOKEN_REFRESH_LEAD


async def refresh_access_token(refresh_token_plain: str) -> oauth.TokenResponse:
    """Thin wrapper around `oauth.refresh_token` — kept here so the publisher
    has one import surface for everything LinkedIn-related."""
    return await oauth.refresh_token(refresh_token_plain)
