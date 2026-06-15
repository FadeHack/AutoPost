"""Cloudflare Workers AI — FLUX-1-schnell adapter (primary AI-image path).

Endpoint (verified June 2026):
  POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/black-forest-labs/flux-1-schnell
  Header: Authorization: Bearer {token}
  Body: {"prompt": "...", "steps": 4}

Response shape:
  {"result": {"image": "<base64-png>"}, "success": true, "errors": [], "messages": []}

Free tier: 10k neurons/day, resets 00:00 UTC. flux-schnell is ~9.6 neurons/step
× 4 steps = ~38 neurons/image → ~260 images/day free. Any 4xx/5xx (including
429 quota-exhausted) raises, so the composer can fall back to Pollinations.
"""
from __future__ import annotations

import base64

import httpx
import structlog

from app.config import settings
from app.rendering.ai_image.interface import ImageGenerator

log = structlog.get_logger(__name__)


class CloudflareConfigError(RuntimeError):
    """Raised when CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_AI_TOKEN are missing."""


class CloudflareFluxGenerator(ImageGenerator):
    """Generate images via Cloudflare Workers AI flux-1-schnell."""

    def __init__(
        self,
        *,
        account_id: str | None = None,
        token: str | None = None,
        model: str | None = None,
        steps: int | None = None,
        timeout: float | None = None,
    ) -> None:
        # Use `is None` (not `or`) so callers can force-test the missing-creds
        # path by explicitly passing "". Falls back to settings only when the
        # caller omits the kwarg entirely.
        self.account_id = settings.CLOUDFLARE_ACCOUNT_ID if account_id is None else account_id
        self.token = settings.CLOUDFLARE_AI_TOKEN if token is None else token
        self.model = settings.AI_IMAGE_MODEL if model is None else model
        self.steps = settings.AI_IMAGE_STEPS if steps is None else steps
        self.timeout = settings.AI_IMAGE_TIMEOUT_SECONDS if timeout is None else timeout

    def _url(self) -> str:
        if not self.account_id or not self.token:
            raise CloudflareConfigError(
                "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_AI_TOKEN must be set"
            )
        return (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{self.account_id}/ai/run/{self.model}"
        )

    async def generate(self, prompt: str) -> bytes:
        url = self._url()
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {"prompt": prompt, "steps": self.steps}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()

        if not data.get("success"):
            raise RuntimeError(
                f"cloudflare flux returned success=false: errors={data.get('errors')}"
            )
        b64 = (data.get("result") or {}).get("image")
        if not b64:
            raise RuntimeError("cloudflare flux response missing result.image")

        png_bytes = base64.b64decode(b64)
        log.info(
            "ai_image.cloudflare.ok",
            model=self.model,
            steps=self.steps,
            bytes=len(png_bytes),
        )
        return png_bytes
