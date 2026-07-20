"""Tiny in-process, in-memory rate limiter (Phase 14).

Deliberately minimal — the only public, unauthenticated write is
`POST /access-requests`, and this backend runs single-process (APScheduler is
in-process; no Redis broker in the MVP). A fixed-window counter keyed by client
IP is enough to blunt casual form spam. It is NOT a distributed limiter and does
not survive a restart; if the deployment ever scales horizontally, swap this for
a shared store. Captcha is deferred (see CHECKLIST Phase 14 Chunk E).
"""

from __future__ import annotations

import threading
import time

from fastapi import Request


class InMemoryRateLimiter:
    """Fixed-window request counter. `allow(key)` returns False once a key has
    exceeded `limit` hits inside the current `window_seconds` bucket."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        # key -> (window_start_epoch, count)
        self._buckets: dict[str, tuple[float, int]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            window_start, count = self._buckets.get(key, (now, 0))
            if now - window_start >= self.window_seconds:
                # Window rolled over — reset.
                window_start, count = now, 0
            count += 1
            self._buckets[key] = (window_start, count)
            return count <= self.limit


def client_ip(request: Request) -> str:
    """Best-effort client IP. Honors the first `X-Forwarded-For` hop (set by the
    reverse proxy in front of the app), falling back to the socket peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
