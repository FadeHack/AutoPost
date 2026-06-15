"""Founder-voice post-processor.

Two layers. Both are idempotent.

1. `strip_ai_tells(text)` — deterministic regex pass. Always cheap, always
   safe to re-run. Returns `(cleaned, violations)` so the caller can decide
   whether to escalate to layer 2.
2. `polish_voice(text)` — optional second LLM pass on the FAST model. Catches
   tonal drift the regex can't (corporate-speak, hedging, summarization habit).
   Called explicitly by the generator only when residual tells warrant it.

All banned phrases / formatting rules trace back to CLAUDE.md "Founder Voice".
"""
from __future__ import annotations

import re

import structlog

from app.config import settings
from app.intelligence import groq_client

log = structlog.get_logger(__name__)


_BANNED_PHRASES: tuple[str, ...] = (
    "delve",
    "moreover",
    "furthermore",
    "it's worth noting",
    "is also worth noting",
    "is worth noting",
    "in today's fast-paced world",
    "navigating the complexities of",
    "i hope this helps",
    "feel free to",
    "it could be argued",
    "one might say",
    "sparked my interest",
    "this got me thinking",
    "got me thinking",
    "i've seen many teams",
    "i've watched many teams",
    "i've seen countless",
    "i've worked with many",
    "i think the problem lies",
    "one notable aspect",
    "the approach used by",
    "this design choice",
    "valuable lesson for anyone",
)

_SUMMARY_OPENERS: tuple[str, ...] = (
    "in summary",
    "in conclusion",
    "to summarize",
    "to conclude",
    "in essence",
    "ultimately,",
    "to sum up",
)


_EM_DASH_SEPARATOR = re.compile(r"\s*—\s*")


def _drop_em_dash_separator(text: str) -> tuple[str, int]:
    """Em-dash with any surrounding whitespace → period + space.

    Em-dashes are the single loudest AI tell because models default to them
    as a clause separator. We don't try to preserve "legitimate" em-dash usage
    (compound modifiers); a human author wouldn't have used one anyway.
    """
    new, n = _EM_DASH_SEPARATOR.subn(". ", text)
    return new, n


def _drop_summary_paragraph(text: str) -> tuple[str, int]:
    """Strip a trailing 'to summarize…' paragraph if present."""
    paragraphs = re.split(r"\n\s*\n", text)
    kept: list[str] = []
    dropped = 0
    for p in paragraphs:
        opener = p.strip().lower()
        if any(opener.startswith(o) for o in _SUMMARY_OPENERS):
            dropped += 1
            continue
        kept.append(p)
    return "\n\n".join(kept), dropped


def _drop_banned_phrases(text: str) -> tuple[str, list[str]]:
    """Remove every banned phrase (case-insensitive) and any trailing comma."""
    found: list[str] = []
    out = text
    for phrase in _BANNED_PHRASES:
        pattern = re.compile(re.escape(phrase) + r"[,;]?\s*", re.IGNORECASE)
        new_out, n = pattern.subn("", out)
        if n > 0:
            found.append(phrase)
            out = new_out
    return out, found


_WS_BEFORE_PUNCT = re.compile(r"\s+([.,!?;:])")
_REPEATED_DOTS = re.compile(r"\.{2,}")
_REPEATED_SPACES = re.compile(r"  +")
_REPEATED_BLANK_LINES = re.compile(r"\n{3,}")
# Capitalize a lowercase letter that starts the string OR follows .!? + whitespace.
# This fixes orphan lowercase starts after a banned-phrase removal at a sentence
# boundary (e.g. "This got me thinking about X" → "about X." → "About X.").
_LOWERCASE_SENTENCE_START = re.compile(r"(^|[.!?]\s+|\n\s*)([a-z])")


def _capitalize_sentence_starts(text: str) -> str:
    return _LOWERCASE_SENTENCE_START.sub(
        lambda m: m.group(1) + m.group(2).upper(), text
    )


def _tidy_whitespace(text: str) -> str:
    text = _WS_BEFORE_PUNCT.sub(r"\1", text)
    text = _REPEATED_DOTS.sub(".", text)
    text = _REPEATED_SPACES.sub(" ", text)
    text = _REPEATED_BLANK_LINES.sub("\n\n", text)
    text = _capitalize_sentence_starts(text)
    return text.strip()


def strip_ai_tells(text: str) -> tuple[str, list[str]]:
    """Deterministic strip. Returns (cleaned_text, list_of_violations_found).

    A violation is appended for each *kind* of tell that fired (em-dash,
    summary, or a specific banned phrase). Use the length of this list to
    decide whether to escalate to `polish_voice`.
    """
    violations: list[str] = []

    text, em_count = _drop_em_dash_separator(text)
    if em_count:
        violations.append("em_dash_separator")

    text, summary_count = _drop_summary_paragraph(text)
    if summary_count:
        violations.append("closing_summary")

    text, banned = _drop_banned_phrases(text)
    violations.extend(banned)

    return _tidy_whitespace(text), violations


_POLISH_SYSTEM = """You are a copy editor for founder-voice LinkedIn posts.

Take the post below and remove any remaining AI-writing tells while preserving the author's voice, opinion, and facts.

Rules:
- No em-dash as a separator. Use a period or line break.
- No closing summary paragraph.
- No "delve", "moreover", "furthermore", "it's worth noting", "navigating the complexities", "in today's fast-paced world", or "I hope this helps".
- No excessive hedging ("it could be argued", "one might say", "perhaps").
- Hooks stay punchy. Short lines.
- Maximum 3 hashtags at the end, lowercase, no spam.

Output the cleaned post text only. No preamble. No explanation. No quotes around the output."""


async def polish_voice(text: str) -> str:
    """Optional second-pass cleanup using GROQ_MODEL_FAST.

    Cheaper than the primary model, suitable for a constrained rewrite where
    the model's job is to enforce a checklist, not to generate new content.
    """
    out = await groq_client.chat(
        stage="polish",
        model=settings.GROQ_MODEL_FAST,
        messages=[
            {"role": "system", "content": _POLISH_SYSTEM},
            {"role": "user", "content": text},
        ],
        temperature=0.3,
        max_tokens=1024,
    )
    # Re-run deterministic strip on polished output (belt and suspenders).
    return strip_ai_tells(out)[0]
