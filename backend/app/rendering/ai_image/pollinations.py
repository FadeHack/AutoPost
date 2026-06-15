"""Pollinations — fallback AI-image adapter, no auth required.

Endpoint (verified June 2026):
  GET https://image.pollinations.ai/prompt/{url-encoded-prompt}?model=flux&width=W&height=H&nologo=true

Returns raw image bytes (image/jpeg or image/png) directly — no JSON wrapper.
Used only when Cloudflare fails or budget is exhausted. Pollinations has had
intermittent Flux outages in 2026 (pollinations/pollinations#8201) so we treat
it strictly as a soft fallback, never as primary.
"""
from __future__ import annotations

from urllib.parse import quote

import httpx
import structlog

from app.config import settings
from app.rendering.ai_image.interface import ImageGenerator

log = structlog.get_logger(__name__)


class PollinationsFluxGenerator(ImageGenerator):
    """Generate images via Pollinations Flux (GET URL, no auth)."""

    def __init__(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self.width = width if width is not None else settings.AI_IMAGE_WIDTH
        self.height = height if height is not None else settings.AI_IMAGE_HEIGHT
        self.timeout = timeout if timeout is not None else settings.AI_IMAGE_TIMEOUT_SECONDS

    def _url(self, prompt: str) -> str:
        encoded = quote(prompt, safe="")
        return (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?model=flux&width={self.width}&height={self.height}&nologo=true"
        )

    async def generate(self, prompt: str) -> bytes:
        url = self._url(prompt)
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            r = await client.get(url)
        r.raise_for_status()

        content_type = r.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            raise RuntimeError(
                f"pollinations returned non-image content-type: {content_type!r}"
            )

        log.info(
            "ai_image.pollinations.ok",
            content_type=content_type,
            bytes=len(r.content),
        )
        return r.content
