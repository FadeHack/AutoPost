"""Tests for the Phase 10 AI-image adapters + composer.

No real network: every test injects an httpx.MockTransport on the per-module
httpx import, mirroring the publishing/test_linkedin_client.py pattern.
"""
from __future__ import annotations

import base64

import httpx
import pytest

from app.rendering.ai_image import (
    CloudflareConfigError,
    CloudflareFluxGenerator,
    PollinationsFluxGenerator,
    generate_image,
)
from app.rendering.ai_image import cloudflare as cf_mod
from app.rendering.ai_image import pollinations as pn_mod
from app.rendering.ai_image.interface import ImageGenerator


PNG_HEADER = b"\x89PNG\r\n\x1a\n"
DUMMY_PNG = PNG_HEADER + b"fake-png-bytes"


@pytest.fixture
def patch_cf_httpx(monkeypatch):
    def _apply(handler):
        real_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(cf_mod.httpx, "AsyncClient", factory)

    return _apply


@pytest.fixture
def patch_pn_httpx(monkeypatch):
    def _apply(handler):
        real_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(pn_mod.httpx, "AsyncClient", factory)

    return _apply


# --- CloudflareFluxGenerator ---


class TestCloudflareFlux:
    @pytest.mark.asyncio
    async def test_happy_path_decodes_base64(self, patch_cf_httpx):
        seen = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["url"] = str(req.url)
            seen["auth"] = req.headers.get("authorization")
            seen["body"] = req.read()
            return httpx.Response(
                200,
                json={
                    "result": {"image": base64.b64encode(DUMMY_PNG).decode()},
                    "success": True,
                    "errors": [],
                    "messages": [],
                },
            )

        patch_cf_httpx(handler)
        gen = CloudflareFluxGenerator(account_id="acc123", token="tok456", steps=4)
        out = await gen.generate("a minimal coffee cup")

        assert out == DUMMY_PNG
        assert "acc123" in seen["url"]
        assert "flux-1-schnell" in seen["url"]
        assert seen["auth"] == "Bearer tok456"
        assert b'"prompt":"a minimal coffee cup"' in seen["body"]
        assert b'"steps":4' in seen["body"]

    @pytest.mark.asyncio
    async def test_missing_creds_raises_config_error(self):
        gen = CloudflareFluxGenerator(account_id="", token="")
        with pytest.raises(CloudflareConfigError):
            await gen.generate("anything")

    @pytest.mark.asyncio
    async def test_http_error_propagates(self, patch_cf_httpx):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"errors": ["rate limited"]})

        patch_cf_httpx(handler)
        gen = CloudflareFluxGenerator(account_id="acc", token="tok")
        with pytest.raises(httpx.HTTPStatusError):
            await gen.generate("x")

    @pytest.mark.asyncio
    async def test_success_false_raises_runtime_error(self, patch_cf_httpx):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"result": None, "success": False, "errors": ["bad prompt"]}
            )

        patch_cf_httpx(handler)
        gen = CloudflareFluxGenerator(account_id="acc", token="tok")
        with pytest.raises(RuntimeError, match="success=false"):
            await gen.generate("x")

    @pytest.mark.asyncio
    async def test_missing_image_field_raises(self, patch_cf_httpx):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"result": {}, "success": True})

        patch_cf_httpx(handler)
        gen = CloudflareFluxGenerator(account_id="acc", token="tok")
        with pytest.raises(RuntimeError, match="result.image"):
            await gen.generate("x")


# --- PollinationsFluxGenerator ---


class TestPollinationsFlux:
    @pytest.mark.asyncio
    async def test_happy_path_returns_raw_bytes(self, patch_pn_httpx):
        seen = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["url"] = str(req.url)
            return httpx.Response(
                200, content=DUMMY_PNG, headers={"content-type": "image/png"}
            )

        patch_pn_httpx(handler)
        gen = PollinationsFluxGenerator(width=800, height=800)
        out = await gen.generate("a minimal coffee cup")

        assert out == DUMMY_PNG
        assert "image.pollinations.ai/prompt/" in seen["url"]
        assert "model=flux" in seen["url"]
        assert "width=800" in seen["url"]
        assert "nologo=true" in seen["url"]
        # URL-encoded prompt (spaces become %20 via quote(safe=""))
        assert "a%20minimal%20coffee%20cup" in seen["url"]

    @pytest.mark.asyncio
    async def test_non_image_content_type_raises(self, patch_pn_httpx):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"<html>oops</html>", headers={"content-type": "text/html"}
            )

        patch_pn_httpx(handler)
        gen = PollinationsFluxGenerator()
        with pytest.raises(RuntimeError, match="non-image content-type"):
            await gen.generate("x")

    @pytest.mark.asyncio
    async def test_http_error_propagates(self, patch_pn_httpx):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(530, content=b"upstream")

        patch_pn_httpx(handler)
        gen = PollinationsFluxGenerator()
        with pytest.raises(httpx.HTTPStatusError):
            await gen.generate("x")


# --- generate_image composer ---


class _StaticGenerator(ImageGenerator):
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> bytes:
        self.calls.append(prompt)
        return self.payload


class _FailingGenerator(ImageGenerator):
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> bytes:
        self.calls.append(prompt)
        raise self.exc


class TestComposer:
    @pytest.mark.asyncio
    async def test_primary_succeeds_fallback_unused(self):
        primary = _StaticGenerator(b"primary-bytes")
        fallback = _StaticGenerator(b"fallback-bytes")

        out = await generate_image("prompt", primary=primary, fallback=fallback)

        assert out == b"primary-bytes"
        assert primary.calls == ["prompt"]
        assert fallback.calls == []

    @pytest.mark.asyncio
    async def test_falls_back_on_primary_http_error(self):
        primary = _FailingGenerator(
            httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("POST", "https://x"),
                response=httpx.Response(429),
            )
        )
        fallback = _StaticGenerator(b"fallback-bytes")

        out = await generate_image("p", primary=primary, fallback=fallback)

        assert out == b"fallback-bytes"
        assert fallback.calls == ["p"]

    @pytest.mark.asyncio
    async def test_falls_back_on_cloudflare_config_error(self):
        primary = _FailingGenerator(CloudflareConfigError("missing creds"))
        fallback = _StaticGenerator(b"fallback-bytes")

        out = await generate_image("p", primary=primary, fallback=fallback)
        assert out == b"fallback-bytes"

    @pytest.mark.asyncio
    async def test_fallback_failure_propagates(self):
        primary = _FailingGenerator(RuntimeError("p down"))
        fallback = _FailingGenerator(RuntimeError("f down"))

        with pytest.raises(RuntimeError, match="f down"):
            await generate_image("p", primary=primary, fallback=fallback)
