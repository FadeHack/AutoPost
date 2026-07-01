"""Five-stage trend → draft pipeline.

Stage 1: angle synthesis    — primary model (llama-3.3-70b-versatile)
Stage 2: founder-voice rewrite — primary model + deterministic AI-tell strip
Stage 3: structured extract → hook/body/tags JSON — FAST model (llama-3.1-8b-instant)
Stage 4: visual extract → pull_quote / metric / carousel_slides JSON — FAST model
Stage 5: AI-image prompt → one short visual prompt string for Flux — primary model (llama-3.3-70b-versatile)

`run_pipeline()` is pure (LLM only, no DB) so it can be unit-tested with a
mocked groq_client. `generate_draft()` wraps it with the DB orchestration:
load active prompt, pick trends, enrich with article bodies, persist Post,
mark source trends consumed.

Stage 4's output goes onto `Post.extracts` and is consumed by the rendering
layer to populate per-template content (pull-quote for `quote_card`, headline
metric for `metric_card`, slide breakdown for `carousel_slide`). The renderer
falls back to `hook` for any field that's null, so Stage 4 failures never
block generation.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.intelligence import article, groq_client, voice
from app.models.base import Platform, PostCategory, PostStatus
from app.models.post import Post
from app.models.post_target import PostTarget
from app.models.prompt import Prompt
from app.models.trend import Trend

log = structlog.get_logger(__name__)

MAX_TRENDS_PER_DRAFT = 3
TRUNCATE_SUMMARY = 500

ANGLE_TEMPERATURE = 0.85
VOICE_TEMPERATURE = 0.7
EXTRACT_TEMPERATURE = 0.0
VISUAL_EXTRACT_TEMPERATURE = 0.2
AI_IMAGE_PROMPT_TEMPERATURE = 0.4

ANGLE_MAX_TOKENS = 500
VOICE_MAX_TOKENS = 450
EXTRACT_MAX_TOKENS = 600
VISUAL_EXTRACT_MAX_TOKENS = 600
AI_IMAGE_PROMPT_MAX_TOKENS = 300  # 30-60 word subject + JSON wrapper

MAX_CAROUSEL_SLIDES = 3

POLISH_ESCALATE_THRESHOLD = 2


_VOICE_REWRITE_SYSTEM = """You are a copy editor rewriting LinkedIn posts in a founder voice.

The voice:
- Contrarian + builder-grounded. One opinion per post.
- The opening line is a REACTION or contrarian OPINION ("Saw a thread…" / "Read a post…" / "Everyone is saying X. Wrong."), NEVER an invented personal achievement or invented stack choice.
- This is a real LinkedIn post: 140-220 words, 4-7 paragraphs. NOT a tweet. NOT a list of 6-word fragments.
- Short lines work for emphasis where one lands. Use full sentences and real paragraphs everywhere else.
- ONE concrete specific somewhere in the middle, drawn from the trend (a number, a name, a quote).
- No closing summary.
- The final takeaway must be SHARP and SPECIFIC. Reject generic affirmations like "AI is real," "simple is better," "humans matter." If your takeaway could fit in any post on any topic, rewrite it.
- No "delve", "moreover", "furthermore", "in conclusion", "it's worth noting".
- Em-dash NEVER as a separator. Use a period or line break.
- 3 hashtags max at the end, lowercase, no spam.

Rewrite the post below. Keep the meaning. Strip the AI-isms. If the input is too short or choppy, EXPAND it into a full LinkedIn-shaped piece.

Output the rewritten post text only. No preamble. No quotes around the output."""


_EXTRACT_SYSTEM = """You extract structured data from a LinkedIn post.

Return strict JSON with these keys:
- "hook": the first line of the post, verbatim
- "body": EVERYTHING AFTER the hook, verbatim, EXCLUDING any trailing hashtag-only line(s). Do NOT repeat the hook. Do NOT include "#tag" lines.
- "tags": array of up to 3 lowercase hashtags WITHOUT the # symbol, extracted from the post's trailing hashtag line (e.g., ["startups", "ai"])

The composed post is rendered as: hook + blank line + body + blank line + #tags. If you include the hook or hashtags in `body`, they will appear twice.

Return only the JSON object. No preamble."""


_HASHTAG_LINE_RE = re.compile(r"^\s*(#\w[\w-]*\s*)+$")


def _strip_trailing_hashtag_lines(text: str) -> str:
    lines = text.rstrip().split("\n")
    while lines and (not lines[-1].strip() or _HASHTAG_LINE_RE.match(lines[-1])):
        lines.pop()
    return "\n".join(lines).rstrip()


def _strip_leading_hook_duplicate(body: str, hook: str) -> str:
    hook_norm = hook.strip().casefold()
    if not hook_norm:
        return body
    lines = body.split("\n")
    # Skip leading blank lines, then drop a single first non-blank line if it matches hook.
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].strip().casefold() == hook_norm:
        del lines[i]
        # Eat any blank lines left behind.
        while i < len(lines) and not lines[i].strip():
            del lines[i]
    return "\n".join(lines).lstrip()


def clean_body(hook: str, body: str) -> str:
    """Remove leading hook duplicate + trailing hashtag-only lines from body.

    Idempotent: safe to apply at generation time AND defensively at publish
    time so legacy drafts (where Stage 3 used to emit body-with-hook) also ship
    cleanly without re-generation.
    """
    return _strip_trailing_hashtag_lines(_strip_leading_hook_duplicate(body, hook))


_VISUAL_EXTRACT_SYSTEM = """You extract per-visual-template content from a finalized LinkedIn post.

The post has already been written. You do not rewrite it. You only extract.

Return a JSON object with these keys exactly:

- "pull_quote": ONE punchy sentence from the post (verbatim or near-verbatim, 8-20 words). The single most opinion-dense or insight-dense line. Prefer a body sentence over the hook if the body has one that's punchier. If nothing in the body beats the hook, return the hook.

- "metric_value": A compact numeric headline IF one is naturally present in the post — a dollar amount, percent, multiplier, large number, or time horizon. Format compactly: "$2,180/mo", "25%", "10x", "10-15 yrs", "50M rows". Return null if the post does not contain a real number. DO NOT invent numbers.

- "metric_label": A 3-7 word label that contextualizes the metric (e.g. "monthly Claude API spend", "of Uber engineering"). Return null if metric_value is null.

- "carousel_slides": An array of EXACTLY 3 slides, each object {"text": "string"}.
    Slide 1 = the hook (verbatim or compressed to <= 14 words).
    Slide 2 = the single sharpest middle beat — the ONE specific or contrarian point that carries the post.
    Slide 3 = the takeaway / reframe.
    Each slide text MUST be <= 14 words. Each slide must be self-contained: a reader who only sees slide 2 should still grasp it without context.

    Return exactly 3 slides. Not 4. Not 5. Three.

Return only the JSON object. No preamble. No explanation."""


# Stage-5 prompt writer. Produces a SUBJECT-only visual prompt following FLUX
# structure (subject → environment → light behavior → lens). It deliberately
# does NOT force a palette or background — the optional brand style is appended
# separately at render time via `AI_IMAGE_BRAND_STYLE_SUFFIX` when
# `settings.AI_IMAGE_BRAND_STYLE` is on. FLUX weights the first tokens most, so
# style modifiers belong at the end (the suffix), not baked into the subject.
_AI_IMAGE_PROMPT_SYSTEM = """You write a visual prompt for the FLUX image model that pairs with a LinkedIn post.

Read the post below. Invent ONE concrete visual that captures its core idea — a single object, a single scene, or a single metaphor. Not a literal illustration of the words.

Return strict JSON:
{
  "ai_image_prompt": "<the visual prompt>"
}

How to write it (FLUX reads natural language, not keyword lists):
- Lead with the SUBJECT. FLUX weights the first words most, so name the main thing first.
- Then describe, in order: what it is doing / the environment around it / how the light behaves (its direction, quality, and the shadows it casts) / a camera or lens reference if the style is photographic.
- 30-60 words. One flowing description, not a bulleted list.
- One subject only. Concrete and grounded.
- Do NOT force a color palette or background color — choose whatever best fits the subject.
- No text, letters, logos, watermarks, or readable signage in the image. No identifiable faces.
- No weight syntax like (word:1.2), no "--" flags, no negatives ("without", "no ...").

Bad: "a vibrant colorful cityscape with people"
Good: "A single frayed climbing rope stretched taut across a weathered wooden workbench, one strand beginning to snap, hard raking light from the left throwing long shadows across the grain, shot on a 50mm lens, shallow depth of field."

Return only the JSON object. No preamble."""


# Optional brand style suffix. Appended to the Stage-5 subject at render time
# only when `settings.AI_IMAGE_BRAND_STYLE` is True, so images composite into
# the minimal-dark brand-wrap per [[project_visual_style]]. Kept as a suffix
# (not baked into the subject) because FLUX weights trailing tokens as global
# style modifiers.
AI_IMAGE_BRAND_STYLE_SUFFIX = (
    "Minimalist editorial photography, deep near-black background, "
    "muted desaturated palette, soft low-key side lighting, subtle film grain."
)

# Fallback prompt used when Stage 5 fails entirely (bad JSON, network error,
# all model attempts produced empty strings). Keeps the brand identity even if
# the LLM goes silent.
_BLUESKY_COMPRESS_SYSTEM = """You rewrite a long LinkedIn-style post into a Bluesky post.

HARD RULES:
- Bluesky character limit is 300 TOTAL (spaces, line breaks, hashtags included). Stay UNDER 280.
- The OPENING LINE must be a contrarian opinion, a reaction, or a sharp claim — NOT a description of what happened. Match the editorial stance of the source. If the source says "X assumption is wrong", the Bluesky version must also say it, in fewer words.
- "Porting X was a wild ride" is WRONG (recap). "Cross-platform is not 'write once run anywhere'. Pointer size will bite you." is RIGHT (opinion).
- ONE opinion per post. No survey. No "this experience highlights…" framing.
- Format: hook (the opinion) + ONE supporting concrete (a number, name, or specific detail from the source). That's it. No paragraphs. No closing summary. No "Lessons:" or "Takeaway:" wrappers.
- 1-2 lowercase hashtags max at the end, or zero if they'd push over the limit.
- Punctuation: NO em-dash (—), NO en-dash (–), NO double-hyphen (--) as a separator. Use a period or line break. Ban: "delve", "moreover", "furthermore", "in conclusion", "it's worth noting".

Output ONLY the rewritten Bluesky post text. No preamble, no surrounding quotes, no "Here is..." opener."""

# Bluesky-target safety net used when the rewrite stage hard-fails or returns
# empty. Long-form Bluesky posts fail loud at publish; a brand-safe one-liner
# gets the draft to a publishable state at least.
_BLUESKY_FALLBACK_COMMENTARY = (
    "Most takes on this miss the point. Builders ship; analysts narrate."
)

# Style-neutral subject used when Stage 5 fails (bad JSON, network error, empty
# output). The brand style suffix is applied separately at render time, so this
# stays palette-neutral like a normal Stage-5 subject.
_AI_IMAGE_PROMPT_FALLBACK = (
    "A single smooth stone resting on a plain flat surface, soft directional "
    "light from one side casting a long shadow, shot on a 50mm lens, shallow "
    "depth of field"
)


def _format_trend(t: Trend, body: str | None) -> str:
    parts = [f"Title: {t.title}", f"URL: {t.url}"]
    if t.summary:
        parts.append(f"Summary: {t.summary[:TRUNCATE_SUMMARY]}")
    if body:
        parts.append(f"Article body:\n{body}")
    return "\n".join(parts)


async def _enrich_trends(trends: list[Trend]) -> list[tuple[Trend, str | None]]:
    results = await asyncio.gather(
        *(article.fetch_article(t.url) for t in trends),
        return_exceptions=True,
    )
    out: list[tuple[Trend, str | None]] = []
    for t, body in zip(trends, results):
        if isinstance(body, BaseException):
            log.warning(
                "generator.article.failed",
                trend_id=str(t.id),
                err=type(body).__name__,
            )
            body = None
        out.append((t, body))
    return out


async def _load_active_prompt(
    session: AsyncSession,
    category: PostCategory,
    platform: Platform | None = None,
) -> Prompt:
    """Matrix lookup (Phase 12). Prefer the per-platform variant
    `(name=category, platform=platform, is_active)`; fall back to the
    `platform IS NULL` "any/legacy" variant when no per-platform row exists
    (graceful for new categories seeded before their full matrix lands).
    Highest active version wins. Raises if neither exists."""
    base = (
        select(Prompt)
        .where(Prompt.category == category)
        .where(Prompt.is_active.is_(True))
        .order_by(Prompt.version.desc())
        .limit(1)
    )
    if platform is not None:
        row = (
            await session.execute(base.where(Prompt.platform == platform))
        ).scalar_one_or_none()
        if row is not None:
            return row
    row = (
        await session.execute(base.where(Prompt.platform.is_(None)))
    ).scalar_one_or_none()
    if row is not None:
        return row
    raise ValueError(
        f"No active prompt for category '{category.value}' "
        f"(platform={platform.value if platform else 'any'})"
    )


async def _load_platform_prompt(
    session: AsyncSession, category: PostCategory, platform: Platform
) -> Prompt | None:
    """Exact per-platform prompt lookup for the Stage-2 commentary rewrite.

    No NULL fallback on purpose: a NULL/legacy prompt is the LinkedIn-shaped
    canonical voice, which is the wrong shape to use as a per-platform rewrite
    system prompt. Returns None when the category has no prompt for `platform`
    yet, so the caller can pick a graceful fallback."""
    stmt = (
        select(Prompt)
        .where(Prompt.category == category)
        .where(Prompt.platform == platform)
        .where(Prompt.is_active.is_(True))
        .order_by(Prompt.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _pick_trends(
    session: AsyncSession,
    trend_ids: list[UUID] | None,
    limit: int,
) -> list[Trend]:
    if trend_ids:
        stmt = select(Trend).where(Trend.id.in_(trend_ids))
        rows = list((await session.execute(stmt)).scalars().all())
        by_id = {r.id: r for r in rows}
        # Preserve caller-supplied order.
        return [by_id[i] for i in trend_ids if i in by_id]
    stmt = (
        select(Trend)
        .where(Trend.consumed_at.is_(None))
        .order_by(nulls_last(Trend.score.desc()), Trend.fetched_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


def _parse_extract(raw: str, fallback_body: str) -> tuple[str, str, list[str]]:
    """Parse Stage 3's JSON. Falls back to (first-line, full-text, []) on bad JSON."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("generator.extract.bad_json", preview=raw[:200])
        first_line = fallback_body.split("\n", 1)[0].strip()
        return first_line, fallback_body, []

    hook = str(parsed.get("hook") or "").strip()
    body = str(parsed.get("body") or fallback_body).strip()
    raw_tags = parsed.get("tags") or []
    if not isinstance(raw_tags, list):
        raw_tags = []
    tags: list[str] = []
    for t in raw_tags:
        norm = str(t).lstrip("#").strip().lower()
        if norm and norm not in tags:
            tags.append(norm)
        if len(tags) >= 3:
            break

    if not hook:
        hook = body.split("\n", 1)[0].strip()

    body = clean_body(hook, body)
    return hook, body, tags


def _str_or_none(value: object) -> str | None:
    """Coerce LLM string-or-null fields. Empty / whitespace becomes None."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def empty_extracts() -> dict[str, Any]:
    """The graceful-fallback shape — every field nullable, slides empty.

    `ai_image_prompt` is intentionally absent here; renderer.py treats missing
    `ai_image_prompt` as the signal to lazily Stage-5-backfill it on demand.
    """
    return {
        "pull_quote": None,
        "metric_value": None,
        "metric_label": None,
        "carousel_slides": [],
    }


def _parse_visual_extract(raw: str) -> dict[str, Any]:
    """Parse Stage 4's JSON into the canonical extracts dict.

    Tolerant: bad JSON, missing keys, wrong types, or bare-string slides all
    degrade gracefully to `empty_extracts()`-shaped output. The renderer then
    falls back to `hook` wherever a field is missing.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("generator.visual_extract.bad_json", preview=raw[:200])
        return empty_extracts()

    if not isinstance(parsed, dict):
        log.warning("generator.visual_extract.bad_shape", preview=raw[:200])
        return empty_extracts()

    out: dict[str, Any] = {
        "pull_quote": _str_or_none(parsed.get("pull_quote")),
        "metric_value": _str_or_none(parsed.get("metric_value")),
        "metric_label": _str_or_none(parsed.get("metric_label")),
        "carousel_slides": [],
    }
    # Metric value and label are co-required — if either is missing, both go.
    if out["metric_value"] is None or out["metric_label"] is None:
        out["metric_value"] = None
        out["metric_label"] = None

    raw_slides = parsed.get("carousel_slides") or []
    if isinstance(raw_slides, list):
        for slide in raw_slides[:MAX_CAROUSEL_SLIDES]:
            if isinstance(slide, dict):
                text = _str_or_none(slide.get("text"))
            elif isinstance(slide, str):
                text = _str_or_none(slide)  # tolerate bare strings
            else:
                text = None
            if text:
                out["carousel_slides"].append({"text": text})

    return out


def _parse_ai_image_prompt(raw: str) -> str | None:
    """Parse Stage 5's JSON. Returns the prompt string, or None on any failure.

    Caller substitutes a brand-safe default when None is returned, so the
    renderer never has to handle a missing prompt mid-flow.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("generator.ai_image_prompt.bad_json", preview=raw[:200])
        return None
    if not isinstance(parsed, dict):
        return None
    return _str_or_none(parsed.get("ai_image_prompt"))


async def extract_ai_image_prompt(
    *,
    voiced_text: str,
    prompt_id: UUID | None = None,
    post_id: UUID | None = None,
) -> str:
    """Run Stage 5 against a finalized post. Returns a non-empty prompt string.

    Falls back to `_AI_IMAGE_PROMPT_FALLBACK` if the model returns bad JSON or
    an empty string. The renderer can trust the return value is always usable.
    Runs on the primary 70B model — the 8B fast tier produced weak, generic
    visual prompts for this task.
    """
    # Primary 70B, not the 8B fast model: writing a concise, evocative 12-25
    # word visual prompt is a small but genuinely creative task the 8B model
    # underperforms on. One ~200-token call per post, so cost is negligible.
    raw = await groq_client.chat(
        stage="ai_image_prompt",
        model=settings.GROQ_MODEL_PRIMARY,
        prompt_id=prompt_id,
        post_id=post_id,
        messages=[
            {"role": "system", "content": _AI_IMAGE_PROMPT_SYSTEM},
            {"role": "user", "content": voiced_text},
        ],
        temperature=AI_IMAGE_PROMPT_TEMPERATURE,
        max_tokens=AI_IMAGE_PROMPT_MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    parsed = _parse_ai_image_prompt(raw)
    if parsed:
        return parsed
    log.warning(
        "generator.ai_image_prompt.fallback_used",
        reason="empty or unparseable Stage 5 output",
    )
    return _AI_IMAGE_PROMPT_FALLBACK


async def extract_visual_fields(
    *,
    voiced_text: str,
    prompt_id: UUID | None = None,
    post_id: UUID | None = None,
) -> dict[str, Any]:
    """Run Stage 4 against a finalized post. Returns the canonical extracts dict.

    Public surface — `render_post` calls this for lazy backfill on older drafts
    that don't have `extracts` yet.
    """
    raw = await groq_client.chat(
        stage="visual_extract",
        model=settings.GROQ_MODEL_FAST,
        prompt_id=prompt_id,
        post_id=post_id,
        messages=[
            {"role": "system", "content": _VISUAL_EXTRACT_SYSTEM},
            {"role": "user", "content": voiced_text},
        ],
        temperature=VISUAL_EXTRACT_TEMPERATURE,
        max_tokens=VISUAL_EXTRACT_MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    return _parse_visual_extract(raw)


async def run_pipeline(
    *,
    prompt: Prompt,
    trends_block: str,
) -> tuple[str, str, list[str], dict[str, Any], list[str]]:
    """Pure LLM pipeline. Returns (hook, body, tags, extracts, violations).

    No DB access. Suitable for unit-tests that mock groq_client.chat.
    """
    angle = await groq_client.chat(
        stage="angle",
        model=settings.GROQ_MODEL_PRIMARY,
        prompt_id=prompt.id,
        messages=[
            {"role": "system", "content": prompt.body},
            {
                "role": "user",
                "content": f"Trends:\n\n{trends_block}\n\nWrite the post now.",
            },
        ],
        temperature=ANGLE_TEMPERATURE,
        max_tokens=ANGLE_MAX_TOKENS,
    )

    voiced_raw = await groq_client.chat(
        stage="voice",
        model=settings.GROQ_MODEL_PRIMARY,
        prompt_id=prompt.id,
        messages=[
            {"role": "system", "content": _VOICE_REWRITE_SYSTEM},
            {"role": "user", "content": angle},
        ],
        temperature=VOICE_TEMPERATURE,
        max_tokens=VOICE_MAX_TOKENS,
    )

    voiced, violations = voice.strip_ai_tells(voiced_raw)
    if violations:
        log.info("generator.tells.stripped", violations=violations)
        if len(violations) >= POLISH_ESCALATE_THRESHOLD:
            voiced = await voice.polish_voice(voiced)
            log.info("generator.voice.polished", violation_count=len(violations))

    extracted = await groq_client.chat(
        stage="extract",
        model=settings.GROQ_MODEL_FAST,
        prompt_id=prompt.id,
        messages=[
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": voiced},
        ],
        temperature=EXTRACT_TEMPERATURE,
        max_tokens=EXTRACT_MAX_TOKENS,
        response_format={"type": "json_object"},
    )

    hook, body, tags = _parse_extract(extracted, voiced)

    extracts = await extract_visual_fields(
        voiced_text=voiced, prompt_id=prompt.id
    )

    # Stage 5 — AI-image prompt. Persisted onto the same extracts JSONB so
    # render_post can switch between template and AI-image kinds without an
    # extra DB lookup. Runs on the primary 70B model for prompt quality.
    ai_image_prompt = await extract_ai_image_prompt(
        voiced_text=voiced, prompt_id=prompt.id
    )
    extracts["ai_image_prompt"] = ai_image_prompt

    return hook, body, tags, extracts, violations


async def compress_for_bluesky(
    *, source_text: str, prompt_id: UUID | None = None
) -> str:
    """Rewrite a LinkedIn-shaped post for Bluesky's 300-char cap.

    Primary 70B + tight system prompt — same reasoning as run_platform_rewrite:
    the 8B fast model overshoots the hard 300-char cap. Falls back to a
    brand-safe one-liner when the rewrite is empty or still over the cap —
    better to ship a publishable Bluesky post than a 1641-char one that fails
    at publish.
    """
    raw = await groq_client.chat(
        stage="bluesky_compress",
        model=settings.GROQ_MODEL_PRIMARY,
        prompt_id=prompt_id,
        messages=[
            {"role": "system", "content": _BLUESKY_COMPRESS_SYSTEM},
            {"role": "user", "content": source_text},
        ],
        temperature=0.5,
        max_tokens=200,
    )
    out = (raw or "").strip().strip('"').strip("'").strip()
    if not out:
        log.warning("generator.bluesky_compress.empty")
        return _BLUESKY_FALLBACK_COMMENTARY
    # The model occasionally returns text > 300 anyway. Treat that as
    # failure and fall back — silently shipping over-cap is worse than
    # shipping the safety net.
    if len(out) > 300:
        log.warning(
            "generator.bluesky_compress.too_long",
            length=len(out),
        )
        return _BLUESKY_FALLBACK_COMMENTARY
    return out


# Canonical platform — when the operator picks multiple platforms, this
# one's content lives on the Post itself. Other platforms get a rewrite
# stored on their PostTarget. LinkedIn always wins canonical when selected
# because the rest of the pipeline (extracts, AI image prompt, carousel
# slides) was designed against LinkedIn-shaped text.
_CANONICAL_ORDER = [
    Platform.linkedin,
    Platform.mastodon,
    Platform.threads,
    Platform.instagram,
    Platform.bluesky,
]


def _canonical_platform(platforms: list[Platform]) -> Platform:
    if not platforms:
        return Platform.linkedin
    chosen = set(platforms)
    for p in _CANONICAL_ORDER:
        if p in chosen:
            return p
    return platforms[0]


# Mirrors each Publisher.char_limit on the backend — keep in sync with the
# publisher classes and frontend PlatformPreview.PLATFORM_LIMITS.
PLATFORM_CHAR_LIMITS: dict[Platform, int] = {
    Platform.linkedin: 3000,
    Platform.bluesky: 300,
    Platform.mastodon: 500,
    Platform.threads: 500,
    Platform.instagram: 2200,
}


async def run_platform_rewrite(
    *,
    prompt: Prompt,
    source_text: str,
    char_limit: int,
    prompt_id: UUID | None = None,
) -> str:
    """Stage-2 voice rewrite for one platform, driven by a DB prompt row.

    The prompt's `body` is the platform-specific voice/shape system prompt
    (Bluesky ≤280, Threads conversational ≤500, Mastodon engineering-leaning
    ≤500, Instagram hashtag-heavy caption). We feed it the canonical
    LinkedIn-shaped post as source material and let it reshape.

    AI-tells are stripped deterministically afterwards. We do NOT truncate to
    the char limit: if a seeded prompt over-shoots, the orchestrator's gate
    fails the target loudly — that's the signal to fix the prompt, not to ship
    a mangled post (project philosophy, see [[project_per_platform_generation_strategy]])."""
    raw = await groq_client.chat(
        stage=f"voice_{prompt.platform.value if prompt.platform else 'any'}",
        # Primary 70B, not the 8B fast model: the per-platform rewrite has to
        # honor a hard char budget (Bluesky ≤300) and the 8B reliably overshoots
        # (e.g. 407 on a 300 cap). The 70B follows the length constraint, and a
        # one-shot rewrite is cheap enough to not need the fast tier.
        model=settings.GROQ_MODEL_PRIMARY,
        prompt_id=prompt_id or prompt.id,
        messages=[
            {"role": "system", "content": prompt.body},
            {"role": "user", "content": source_text},
        ],
        temperature=0.5,
        max_tokens=min(800, max(200, char_limit // 3)),
    )
    out, violations = voice.strip_ai_tells(raw or "")
    out = out.strip().strip('"').strip("'").strip()
    if violations:
        log.info("generator.platform_rewrite.tells_stripped", violations=violations)
    if len(out) > char_limit:
        log.warning(
            "generator.platform_rewrite.over_cap",
            platform=prompt.platform.value if prompt.platform else "any",
            length=len(out),
            cap=char_limit,
        )
    return out


async def _build_platform_commentary(
    session: AsyncSession,
    category: PostCategory,
    platform: Platform,
    *,
    source_text: str,
    prompt_id: UUID | None = None,
) -> str | None:
    """Per-platform commentary for one target (Phase 12: DB-prompt-driven).

    LinkedIn → None: the orchestrator assembles the canonical Post hook/body/
    tags, which is already the LinkedIn artifact.

    Other platforms → load the per-platform prompt and run a proper Stage-2
    rewrite. When a category has no per-platform prompt yet, fall back
    gracefully: Bluesky keeps the legacy `compress_for_bluesky` so existing
    categories still publish; Mastodon/Threads/Instagram return None (fall back
    to the LinkedIn-shaped Post.body and trip the char-limit gate loudly until
    their prompt is seeded — intentional pressure, not a bug)."""
    if platform == Platform.linkedin:
        return None
    prompt = await _load_platform_prompt(session, category, platform)
    if prompt is not None:
        return await run_platform_rewrite(
            prompt=prompt,
            source_text=source_text,
            char_limit=PLATFORM_CHAR_LIMITS[platform],
        )
    if platform == Platform.bluesky:
        return await compress_for_bluesky(
            source_text=source_text, prompt_id=prompt_id
        )
    return None


async def generate_draft(
    session: AsyncSession,
    *,
    category: PostCategory,
    trend_ids: list[UUID] | None = None,
    platforms: list[Platform] | None = None,
    max_trends: int = MAX_TRENDS_PER_DRAFT,
) -> Post:
    """Pick trends, run pipeline, persist draft + PostTargets, mark
    source trends consumed.

    `platforms` (default `[Platform.linkedin]`) drives both:
    - which PostTarget rows are pre-created on the draft, and
    - per-platform commentary rewriting (Bluesky gets compressed inline).
    Operator confirms the picks by approving the draft later.
    """
    platforms = platforms or [Platform.linkedin]
    # De-dupe but preserve order so the canonical resolver is deterministic.
    seen: set[Platform] = set()
    picked_platforms: list[Platform] = []
    for p in platforms:
        if p not in seen:
            seen.add(p)
            picked_platforms.append(p)
    if not picked_platforms:
        raise ValueError("at least one platform required")

    # Canonical Post is always the LinkedIn artifact (Stage 3/4/5 + rendering
    # are LinkedIn-shaped). Load the LinkedIn prompt variant, falling back to
    # the platform=NULL legacy prompt for categories without a full matrix.
    prompt = await _load_active_prompt(session, category, platform=Platform.linkedin)

    picked = await _pick_trends(session, trend_ids, limit=max_trends)
    if not picked:
        raise ValueError("No trends available for generation")
    picked = picked[:max_trends]

    enriched = await _enrich_trends(picked)
    trends_block = "\n\n---\n\n".join(
        _format_trend(t, body) for t, body in enriched
    )

    hook, body, tags, extracts, _violations = await run_pipeline(
        prompt=prompt,
        trends_block=trends_block,
    )

    canonical_text = f"{hook.strip()}\n\n{body.strip()}"

    post = Post(
        category=category,
        hook=hook[:512],
        body=body,
        tags=tags,
        extracts=extracts,
        source_trend_ids=[t.id for t in picked],
        status=PostStatus.draft,
    )
    session.add(post)
    await session.flush()  # need post.id for the PostTarget FK below.

    # NOTE: we do NOT skip _build_platform_commentary for the "canonical"
    # platform. Stage 2 is hardcoded LinkedIn-voice so Post.body is always
    # LinkedIn-shaped — even a Bluesky-only draft. Each non-LinkedIn target
    # needs its own commentary or the orchestrator's char-limit gate fails
    # at publish. LinkedIn target keeps commentary=None (falls back to Post).
    for platform in picked_platforms:
        commentary = await _build_platform_commentary(
            session,
            category,
            platform,
            source_text=canonical_text,
            prompt_id=prompt.id,
        )
        session.add(
            PostTarget(
                post_id=post.id,
                platform=platform,
                commentary=commentary,
            )
        )

    now = datetime.now(timezone.utc)
    for t in picked:
        t.consumed_at = now

    await session.commit()
    await session.refresh(post)
    return post
