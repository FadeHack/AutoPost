"""Tests for the Groq client wrapper.

We never hit the network — `_client()` is monkeypatched to return a stub,
and `_log_generation()` is replaced with a recorder so we can assert on the
audit payload without touching the DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from groq import APIConnectionError, RateLimitError

from app.intelligence import groq_client


@dataclass
class _StubUsage:
    prompt_tokens: int = 42
    completion_tokens: int = 7


@dataclass
class _StubMessage:
    content: str = "hello world"


@dataclass
class _StubChoice:
    message: _StubMessage = field(default_factory=_StubMessage)


@dataclass
class _StubResponse:
    choices: list[_StubChoice] = field(default_factory=lambda: [_StubChoice()])
    usage: _StubUsage | None = field(default_factory=_StubUsage)


class _StubCompletions:
    def __init__(self, *, response=None, raises: list[Exception] | None = None):
        self._response = response or _StubResponse()
        self._raises = list(raises or [])
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise self._raises.pop(0)
        return self._response


class _StubChat:
    def __init__(self, completions):
        self.completions = completions


class _StubClient:
    def __init__(self, completions):
        self.chat = _StubChat(completions)


@pytest.fixture
def audit_recorder(monkeypatch):
    """Replace _log_generation with a recorder; capture every audit row."""
    recorded: list[dict[str, Any]] = []

    async def _record(**kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(groq_client, "_log_generation", _record)
    return recorded


@pytest.fixture
def stub_client(monkeypatch):
    """Install a stub Groq client. Returns a setter so tests configure it."""
    holder: dict[str, _StubClient] = {}

    def install(*, response=None, raises=None):
        completions = _StubCompletions(response=response, raises=raises)
        client = _StubClient(completions)
        holder["client"] = client
        monkeypatch.setattr(groq_client, "_client", lambda: client)
        return completions

    return install


async def test_happy_path_returns_content_and_records_audit(stub_client, audit_recorder):
    completions = stub_client()
    out = await groq_client.chat(
        stage="angle",
        messages=[{"role": "user", "content": "hi"}],
        model="llama-3.3-70b-versatile",
        temperature=0.5,
        max_tokens=128,
    )
    assert out == "hello world"

    # Client got the right kwargs
    assert len(completions.calls) == 1
    call = completions.calls[0]
    assert call["model"] == "llama-3.3-70b-versatile"
    assert call["temperature"] == 0.5
    assert call["max_tokens"] == 128
    assert call["messages"] == [{"role": "user", "content": "hi"}]

    # Audit captured input, output, tokens, stage
    assert len(audit_recorder) == 1
    audit = audit_recorder[0]
    assert audit["stage"] == "angle"
    assert audit["model"] == "llama-3.3-70b-versatile"
    assert audit["output_text"] == "hello world"
    assert audit["tokens_in"] == 42
    assert audit["tokens_out"] == 7
    assert audit["latency_ms"] >= 0
    assert "[user]\nhi" in audit["input_text"]


async def test_default_model_falls_back_to_settings(stub_client, audit_recorder):
    stub_client()
    await groq_client.chat(stage="x", messages=[{"role": "user", "content": "q"}])
    assert audit_recorder[0]["model"]  # whatever GROQ_MODEL_PRIMARY is, it must be set


async def test_response_format_passed_through(stub_client, audit_recorder):
    completions = stub_client()
    await groq_client.chat(
        stage="extract",
        messages=[{"role": "user", "content": "q"}],
        response_format={"type": "json_object"},
    )
    assert completions.calls[0]["response_format"] == {"type": "json_object"}


async def test_response_format_omitted_when_none(stub_client, audit_recorder):
    completions = stub_client()
    await groq_client.chat(stage="x", messages=[{"role": "user", "content": "q"}])
    assert "response_format" not in completions.calls[0]


async def test_reasoning_effort_auto_set_for_qwen(stub_client, audit_recorder):
    completions = stub_client()
    await groq_client.chat(
        stage="voice",
        messages=[{"role": "user", "content": "q"}],
        model="qwen/qwen3.6-27b",
    )
    # qwen reasons by default — client must pin it off or JSON stages break.
    assert completions.calls[0]["reasoning_effort"] == "none"


async def test_reasoning_effort_low_for_gpt_oss(stub_client, audit_recorder):
    completions = stub_client()
    await groq_client.chat(
        stage="x",
        messages=[{"role": "user", "content": "q"}],
        model="openai/gpt-oss-120b",
    )
    assert completions.calls[0]["reasoning_effort"] == "low"


async def test_reasoning_effort_omitted_for_non_reasoning_model(stub_client, audit_recorder):
    completions = stub_client()
    await groq_client.chat(
        stage="x",
        messages=[{"role": "user", "content": "q"}],
        model="meta-llama/llama-4-scout-17b-16e-instruct",
    )
    # llama rejects reasoning_effort — it must not be sent.
    assert "reasoning_effort" not in completions.calls[0]


async def test_reasoning_effort_explicit_override(stub_client, audit_recorder):
    completions = stub_client()
    await groq_client.chat(
        stage="x",
        messages=[{"role": "user", "content": "q"}],
        model="qwen/qwen3.6-27b",
        reasoning_effort="low",
    )
    assert completions.calls[0]["reasoning_effort"] == "low"


async def test_non_retryable_error_propagates_and_still_audits(
    stub_client, audit_recorder
):
    # ValueError isn't in _RETRYABLE, so it should bubble out on the first try.
    stub_client(raises=[ValueError("boom")])

    with pytest.raises(ValueError, match="boom"):
        await groq_client.chat(
            stage="angle", messages=[{"role": "user", "content": "hi"}]
        )

    # Audit row still recorded with error in output_text.
    assert len(audit_recorder) == 1
    assert audit_recorder[0]["output_text"].startswith("<error:ValueError>")


async def test_retryable_error_then_success(stub_client, audit_recorder, monkeypatch):
    # Make tenacity sleep zero so retries are fast.
    async def _zero_sleep(*_a, **_kw):
        return None

    monkeypatch.setattr("tenacity.nap.time.sleep", lambda *_a, **_kw: None)

    # Build a RateLimitError without needing a real Response — just construct
    # the bare exception class.
    rl = RateLimitError.__new__(RateLimitError)
    Exception.__init__(rl, "slow down")

    completions = stub_client(raises=[rl])  # one transient failure, then success
    out = await groq_client.chat(
        stage="angle", messages=[{"role": "user", "content": "hi"}]
    )
    assert out == "hello world"
    assert len(completions.calls) == 2  # one retry happened
    assert len(audit_recorder) == 1  # one audit row per chat() call


async def test_missing_api_key_raises(monkeypatch, audit_recorder):
    from app.intelligence import groq_client as gc
    from app.config import settings

    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    # Restore the real _client (the audit fixture leaves it alone, but stub_client
    # fixture isn't used here).
    monkeypatch.setattr(gc, "_client", gc._client.__wrapped__ if hasattr(gc._client, "__wrapped__") else gc._client)

    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        await gc.chat(stage="x", messages=[{"role": "user", "content": "q"}])
