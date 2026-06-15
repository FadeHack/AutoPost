"""ABC for AI image generation backends.

Phase 10 ships two impls (Cloudflare Workers AI primary, Pollinations fallback)
in Chunk B. Both will conform to this single-method contract so the composer
can fall back without leaking vendor specifics into the renderer.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class ImageGenerator(ABC):
    """Generate raw PNG/JPEG bytes from a short text prompt.

    The prompt is the Stage-5 visual-prompt string (~1 sentence). Implementations
    raise on transport/auth failure so the composer can route to the next vendor.
    They do NOT retry internally — retry policy belongs to the composer.
    """

    @abstractmethod
    async def generate(self, prompt: str) -> bytes:
        """Return raw image bytes. Square aspect, ~800px target.

        Raises:
            httpx.HTTPError: transport failure
            RuntimeError: vendor returned a non-image response
        """
        raise NotImplementedError
