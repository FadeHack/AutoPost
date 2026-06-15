"""Supabase Storage client for rendered post visuals.

The bucket is *public* (renders are branded marketing artifacts that end up on
public LinkedIn). Public buckets are CDN-fronted by Supabase and bypass RLS for
reads, so we get fast cached fetches without signed-URL round trips.

Writes are authenticated with `SUPABASE_SERVICE_ROLE_KEY`, which bypasses
storage RLS — same key we use for the DB. No new credential needed.

The official `supabase-py` SDK is sync; every call is wrapped in
`asyncio.to_thread()` to keep the async-by-default backend conventions.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

import structlog
from supabase import Client, create_client

from app.config import settings

log = structlog.get_logger(__name__)

# Module-level client + lock. Lazy-init on first call so test environments
# without Supabase creds don't fail at import time.
_client: Client | None = None
_lock = threading.Lock()


def _get_client() -> Client:
    global _client
    with _lock:
        if _client is None:
            if not settings.SUPABASE_URL:
                raise RuntimeError(
                    "SUPABASE_URL is not configured — cannot upload to storage"
                )
            if not settings.SUPABASE_SERVICE_ROLE_KEY:
                raise RuntimeError(
                    "SUPABASE_SERVICE_ROLE_KEY is not configured — needed for "
                    "backend storage writes (bypasses RLS)"
                )
            _client = create_client(
                settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY
            )
            log.info("supabase_storage.client_created", url=settings.SUPABASE_URL)
        return _client


def _public_url_for(path: str) -> str:
    """Construct the public URL for a bucket path. No network call."""
    base = settings.SUPABASE_URL.rstrip("/")
    bucket = settings.SUPABASE_STORAGE_BUCKET
    return f"{base}/storage/v1/object/public/{bucket}/{path}"


def _upload_sync(path: str, png_bytes: bytes) -> dict[str, Any]:
    client = _get_client()
    return client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).upload(
        path=path,
        file=png_bytes,
        file_options={
            "content-type": "image/png",
            # Asset IDs are uuid4 — collisions impossible, so upsert=false
            # treats any unexpected collision as a bug worth surfacing.
            "upsert": "false",
        },
    )


async def upload_png(path: str, png_bytes: bytes) -> str:
    """Upload PNG bytes to the configured bucket under `path`. Returns public URL.

    `path` is the within-bucket key, e.g. `<post_id>/<asset_id>.png`. The renderer
    builds this; storage just stores it.
    """
    await asyncio.to_thread(_upload_sync, path, png_bytes)
    url = _public_url_for(path)
    log.info(
        "supabase_storage.uploaded",
        path=path,
        bytes=len(png_bytes),
        url=url,
    )
    return url


def public_url(path: str) -> str:
    """Public-URL constructor exposed for the API schema layer."""
    return _public_url_for(path)
