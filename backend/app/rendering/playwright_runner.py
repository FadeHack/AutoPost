"""Singleton Playwright + Chromium owned by the app process.

Booting a fresh Chromium per render costs ~3 seconds. One process-wide instance
amortizes that cost across every render call. Started from FastAPI's `lifespan`
hook so it shares the app lifecycle exactly.

`html_to_png(html, width, height)` is the only call site renderers should use.
It opens a throwaway page, paints, screenshots, closes — never returning the
page object so callers can't accidentally hold a reference to a closed browser.
"""
from __future__ import annotations

import asyncio

import structlog
from playwright.async_api import Browser, Playwright, async_playwright

log = structlog.get_logger(__name__)


_playwright: Playwright | None = None
_browser: Browser | None = None
_lock = asyncio.Lock()


async def start() -> None:
    """Boot Playwright + a single headless Chromium. Idempotent."""
    global _playwright, _browser
    async with _lock:
        if _browser is not None:
            return
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)
        log.info("playwright.started", browser="chromium")


async def stop() -> None:
    """Tear the browser + driver down. Safe to call if start() never ran.

    Shutdown cleanup is best-effort: on Ctrl+C the SIGINT hits the whole
    process group, so the Playwright Node driver subprocess often dies before
    we get here. By then `_browser.close()` raises `RuntimeError: ... the
    handler is closed` because the IPC transport is already gone. The browser
    process is already reaped — log and move on, don't crash shutdown."""
    global _playwright, _browser
    async with _lock:
        if _browser is not None:
            try:
                await _browser.close()
            except Exception as e:
                log.debug("playwright.browser_close_failed", error=str(e))
            _browser = None
        if _playwright is not None:
            try:
                await _playwright.stop()
            except Exception as e:
                log.debug("playwright.driver_stop_failed", error=str(e))
            _playwright = None
        log.info("playwright.stopped")


async def html_to_png(
    html: str,
    *,
    width: int,
    height: int,
    device_scale_factor: int = 2,
) -> bytes:
    """Render an HTML string to a PNG byte string at `width × height` logical px.

    `device_scale_factor=2` produces a 2× image (retina-crisp at LinkedIn's
    display size). Returned bytes are PNG-encoded.

    Each call uses its own browser context so isolation is total — no cookie /
    localStorage / cache bleed between renders. The browser process itself is
    reused.
    """
    if _browser is None:
        raise RuntimeError(
            "playwright_runner not started. Did the FastAPI lifespan hook fail?"
        )
    context = await _browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=device_scale_factor,
    )
    try:
        page = await context.new_page()
        # `load` is enough — set_content waits for it by default. Tailwind CDN
        # injects a <style> synchronously after parse, so we also wait for
        # networkidle to make sure the CDN response has settled before screenshot.
        await page.set_content(html, wait_until="networkidle")
        return await page.screenshot(type="png", full_page=False)
    finally:
        await context.close()
