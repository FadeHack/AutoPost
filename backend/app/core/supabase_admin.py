"""Supabase Auth **admin** client — service_role, server-only (Phase 14 Chunk F).

Used by the /admin approve flow to send a magic-link invite to a newly approved
email. `invite_user_by_email` creates the Supabase Auth user (if absent) and
mails them the accept link; the returned user id is the same UUID we key our
local `users` row on, so first login's JIT path finds the row and lets them in.

The official `supabase-py` SDK is sync (verified against 2.13.0 —
`supabase.auth.admin.invite_user_by_email(email, options={"redirect_to": ...})`),
so every call is wrapped in `asyncio.to_thread()` to keep the async backend
conventions. The service_role key bypasses RLS — it must never reach the browser.
"""
from __future__ import annotations

import asyncio
import threading
import uuid

import structlog
from gotrue.errors import AuthError
from supabase import Client, create_client

from app.config import settings

log = structlog.get_logger(__name__)

# Module-level client + lock. Lazy-init on first call so test/dev environments
# without Supabase creds don't fail at import time (mirrors rendering/storage.py).
_client: Client | None = None
_lock = threading.Lock()


class SupabaseAdminError(RuntimeError):
    """Raised when the admin invite call fails (misconfig or Supabase-side error)."""


def _get_client() -> Client:
    global _client
    with _lock:
        if _client is None:
            if not settings.SUPABASE_URL:
                raise SupabaseAdminError("SUPABASE_URL is not configured")
            if not settings.SUPABASE_SERVICE_ROLE_KEY:
                raise SupabaseAdminError(
                    "SUPABASE_SERVICE_ROLE_KEY is not configured — needed to "
                    "invite users (service_role, bypasses RLS)"
                )
            _client = create_client(
                settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY
            )
            log.info("supabase_admin.client_created", url=settings.SUPABASE_URL)
        return _client


def _invite_sync(email: str, redirect_to: str | None) -> uuid.UUID:
    client = _get_client()
    options: dict = {}
    if redirect_to:
        options["redirect_to"] = redirect_to
    try:
        resp = client.auth.admin.invite_user_by_email(email, options)
    except AuthError as e:
        # gotrue raises its own AuthApiError (e.g. invalid/duplicate email, rate
        # limit). Normalize to SupabaseAdminError so the caller maps it to a clean
        # 502 instead of a 500 — `str(e)` carries the human-readable reason.
        raise SupabaseAdminError(str(e)) from e
    if resp is None or resp.user is None or resp.user.id is None:
        raise SupabaseAdminError("invite returned no user")
    return uuid.UUID(str(resp.user.id))


async def invite_user_by_email(
    email: str, *, redirect_to: str | None = None
) -> uuid.UUID:
    """Send a magic-link invite and return the Supabase Auth user's UUID.

    The UUID is what we key the local `users` row on, so JIT login recognizes the
    invitee. Raises `SupabaseAdminError` on any failure (the caller maps it to an
    HTTP error). `redirect_to` is where the accept link lands (the dashboard)."""
    user_id = await asyncio.to_thread(_invite_sync, email, redirect_to)
    log.info("supabase_admin.invited", email=email, user_id=str(user_id))
    return user_id
