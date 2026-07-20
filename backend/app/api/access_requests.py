"""Public access-request intake (Phase 14, invite-only).

The ONE unauthenticated write in the API. A logged-out visitor submits their
email (+ optional name/company/reason) from the marketing landing; the row lands
`pending` for an admin to approve in `/admin` (Chunk F). No auth dependency here
by design — everything else in the app is JWT-gated.

Spam guards (captcha deferred):
  * Honeypot — a hidden `website` field real users never fill; a non-empty value
    means a bot, so we 202 (look successful) but persist nothing.
  * IP rate limit — a fixed-window per-IP cap (see `core/ratelimit.py`).
Duplicate-safe: a repeat email with a still-`pending` request is a no-op 202 (no
row spam, no existence leak about prior submissions).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.ratelimit import InMemoryRateLimiter, client_ip
from app.db import get_session
from app.models.access_request import AccessRequest
from app.models.base import AccessRequestStatus

router = APIRouter(prefix="/access-requests", tags=["access-requests"])
log = get_logger("api.access_requests")

# 5 submissions per IP per hour — generous for a human, hostile to a script.
_limiter = InMemoryRateLimiter(limit=5, window_seconds=3600)

# Pragmatic email shape check — we avoid the `email-validator` dependency (not in
# requirements). Deliverability is proven anyway by the Supabase magic-link invite.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccessRequestCreate(BaseModel):
    email: str = Field(max_length=320)
    name: str | None = Field(default=None, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=2000)
    # Honeypot: must stay empty. Named to look like a real field to bots.
    website: str | None = Field(default=None, max_length=255)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("invalid email address")
        return v


class AccessRequestAck(BaseModel):
    """Intentionally opaque — same shape whether we stored, deduped, or dropped a
    bot, so nothing leaks about who has already requested access."""
    ok: bool = True


@router.post("", response_model=AccessRequestAck, status_code=status.HTTP_202_ACCEPTED)
async def create_access_request(
    payload: AccessRequestCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AccessRequestAck:
    ip = client_ip(request)
    if not _limiter.allow(ip):
        log.warning("access_request.rate_limited", ip=ip)
        # Uniform ack — don't hand a scraper a signal to back off precisely.
        return AccessRequestAck()

    if payload.website:
        # Honeypot tripped — silently drop.
        log.warning("access_request.honeypot", ip=ip)
        return AccessRequestAck()

    email = payload.email.lower().strip()

    # Dedupe: if an open (pending) request already exists for this email, no-op.
    existing = (
        await session.execute(
            select(AccessRequest.id).where(
                AccessRequest.email == email,
                AccessRequest.status == AccessRequestStatus.pending,
            )
        )
    ).first()
    if existing is not None:
        log.info("access_request.duplicate", email=email)
        return AccessRequestAck()

    req = AccessRequest(
        email=email,
        name=(payload.name or None),
        company=(payload.company or None),
        reason=(payload.reason or None),
    )
    session.add(req)
    await session.commit()
    log.info("access_request.created", email=email)
    return AccessRequestAck()
