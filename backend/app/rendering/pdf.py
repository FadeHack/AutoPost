"""PNG-list-to-PDF assembly for LinkedIn document-post carousels.

LinkedIn's swipeable carousel is a Document post (PDF), not a MultiImage post.
This module turns a list of slide PNGs into a single multi-page PDF that can
be uploaded via the Documents API.

`img2pdf` is the right tool: lossless (no re-encoding), tiny dep, accepts raw
PNG bytes. CPU-bound work runs in a thread to keep the FastAPI event loop free.
"""
from __future__ import annotations

import asyncio
from typing import Sequence

import img2pdf


def _build_pdf_sync(pngs: Sequence[bytes]) -> bytes:
    if not pngs:
        raise ValueError("pdf.build: at least one PNG is required")
    return img2pdf.convert(list(pngs))


async def build_pdf(pngs: Sequence[bytes]) -> bytes:
    """Assemble PNG bytes into a multi-page PDF, one PNG per page, in order."""
    return await asyncio.to_thread(_build_pdf_sync, pngs)
