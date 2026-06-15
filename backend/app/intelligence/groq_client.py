"""Async Groq wrapper.

One entry point: `chat(...)`. Every call writes an `ai_generations` audit row
regardless of success or failure, so the DB is the single source of truth for
what the LLM saw and produced. Retries on connection / rate-limit errors with
exponential backoff. 4xx (auth, malformed request) is *not* retried.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from groq import APIConnectionError, APIError, AsyncGroq, RateLimitError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.ai_generation import AIGeneration

log = structlog.get_logger(__name__)

_RETRYABLE = (APIConnectionError, RateLimitError)


def _client() -> AsyncGroq:
    if not settings.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set in backend/.env")
    return AsyncGroq(api_key=settings.GROQ_API_KEY)


async def _log_generation(
    *,
    stage: str,
    model: str,
    input_text: str,
    output_text: str,
    tokens_in: int | None,
    tokens_out: int | None,
    latency_ms: int,
    post_id: uuid.UUID | None,
    prompt_id: uuid.UUID | None,
) -> None:
    """Insert an audit row. Failures are logged, never raised."""
    try:
        async with AsyncSessionLocal() as session:
            session.add(
                AIGeneration(
                    post_id=post_id,
                    prompt_id=prompt_id,
                    stage=stage,
                    model=model,
                    input=input_text,
                    output=output_text,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                )
            )
            await session.commit()
    except Exception:
        log.exception("groq.audit.failed", stage=stage, model=model)


async def chat(
    *,
    stage: str,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    response_format: dict[str, Any] | None = None,
    post_id: uuid.UUID | None = None,
    prompt_id: uuid.UUID | None = None,
) -> str:
    """Single chat completion. Returns the assistant message content.

    `stage` is the pipeline-phase label (e.g. 'angle', 'voice', 'extract')
    and is recorded on every audit row.
    """
    chosen_model = model or settings.GROQ_MODEL_PRIMARY
    client = _client()

    input_text = "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in messages)

    start = time.perf_counter()
    output_text = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    error: Exception | None = None

    try:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(_RETRYABLE),
            stop=stop_after_attempt(4),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        ):
            with attempt:
                kwargs: dict[str, Any] = {
                    "model": chosen_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if response_format is not None:
                    kwargs["response_format"] = response_format
                resp = await client.chat.completions.create(**kwargs)
                output_text = resp.choices[0].message.content or ""
                if resp.usage is not None:
                    tokens_in = resp.usage.prompt_tokens
                    tokens_out = resp.usage.completion_tokens
    except Exception as e:
        error = e
        output_text = f"<error:{type(e).__name__}> {e}"
        raise
    finally:
        latency_ms = int((time.perf_counter() - start) * 1000)
        await _log_generation(
            stage=stage,
            model=chosen_model,
            input_text=input_text,
            output_text=output_text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            post_id=post_id,
            prompt_id=prompt_id,
        )
        if error is None:
            log.info(
                "groq.chat.ok",
                stage=stage,
                model=chosen_model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
            )
        else:
            log.warning(
                "groq.chat.failed",
                stage=stage,
                model=chosen_model,
                err=type(error).__name__,
                latency_ms=latency_ms,
            )

    return output_text


__all__ = ["chat", "APIError", "APIConnectionError", "RateLimitError"]
