"""AI image generation (Phase 10).

`generate_image(prompt)` is the public entry point. It runs Cloudflare first;
on any failure (config, transport, quota, vendor error), it logs the failure
mode and falls back to Pollinations. Returns raw image bytes regardless of
which vendor served the request.
"""
from __future__ import annotations

import structlog

from app.rendering.ai_image.cloudflare import (
    CloudflareConfigError,
    CloudflareFluxGenerator,
)
from app.rendering.ai_image.interface import ImageGenerator
from app.rendering.ai_image.pollinations import PollinationsFluxGenerator

log = structlog.get_logger(__name__)

__all__ = [
    "ImageGenerator",
    "CloudflareFluxGenerator",
    "CloudflareConfigError",
    "PollinationsFluxGenerator",
    "generate_image",
]


async def generate_image(
    prompt: str,
    *,
    primary: ImageGenerator | None = None,
    fallback: ImageGenerator | None = None,
) -> bytes:
    """Run primary, fall back on failure. Default chain: Cloudflare → Pollinations.

    Tests inject mock generators via `primary` / `fallback`. If primary raises
    `CloudflareConfigError` (missing creds), we silently route to the fallback —
    that's expected when the operator hasn't configured Cloudflare yet. All
    other failures are logged at WARNING with the exception class name.
    """
    primary = primary or CloudflareFluxGenerator()
    fallback = fallback or PollinationsFluxGenerator()

    try:
        return await primary.generate(prompt)
    except Exception as e:  # noqa: BLE001 — composer logs and falls through deliberately
        log.warning(
            "ai_image.primary_failed",
            vendor=type(primary).__name__,
            error_class=type(e).__name__,
            error=str(e),
        )

    bytes_ = await fallback.generate(prompt)
    log.info("ai_image.fallback_used", vendor=type(fallback).__name__)
    return bytes_
