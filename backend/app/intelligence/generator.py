"""Five-stage trend → draft pipeline.

Stage 1: angle synthesis    — primary model (llama-3.3-70b-versatile)
Stage 2: founder-voice rewrite — primary model + deterministic AI-tell strip
Stage 3: structured extract → hook/body/tags JSON — FAST model (llama-3.1-8b-instant)
Stage 4: visual extract → pull_quote / metric / carousel_slides JSON — FAST model
Stage 5: AI-image prompt → one short visual prompt string for Flux — FAST model

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
AI_IMAGE_PROMPT_MAX_TOKENS = 200

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


# Brand visual identity per [[project_visual_style]] — minimal dark. The model
# must respect this so generated images composite cleanly inside the brand-wrap
# template (black bg, serif headline, sans body, accent line above brand strap).
_AI_IMAGE_PROMPT_SYSTEM = """You write a short visual prompt for an AI image generator (Flux).

Read the LinkedIn post below. Produce ONE concrete visual that pairs with it.

Return strict JSON:
{
  "ai_image_prompt": "<one sentence visual prompt, 12-25 words>"
}

Rules:
- Minimal, dark, editorial. Black or near-black background. Soft contrast.
- One subject. Concrete and grounded — a single object, a single scene, a single metaphor.
- Photographic OR minimalist illustration style. Never cartoon. Never collage.
- No text in the image. No logos. No watermarks. No people's faces.
- 12-25 words. No preamble, no apology, no "an image of".
- The prompt should make sense even if a reader never sees the post.

Bad: "a vibrant colorful cityscape with people"
Good: "a single empty coffee cup on a dark wooden desk, soft side light, shallow depth of field"
Good: "minimalist illustration of a rope being cut by scissors, off-white on near-black, high contrast"

Return only the JSON object. No preamble."""

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

_AI_IMAGE_PROMPT_FALLBACK = (
    "minimalist editorial illustration on a near-black background, "
    "soft contrast, one subject centered, no text"
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
    session: AsyncSession, category: PostCategory
) -> Prompt:
    stmt = (
        select(Prompt)
        .where(Prompt.category == category)
        .where(Prompt.is_active.is_(True))
        .order_by(Prompt.version.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise ValueError(f"No active prompt for category '{category.value}'")
    return row


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
    Cost target: <$0.0002/post on `llama-3.1-8b-instant`.
    """
    raw = await groq_client.chat(
        stage="ai_image_prompt",
        model=settings.GROQ_MODEL_FAST,
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
    # extra DB lookup. Cheap (<$0.0002 on llama-3.1-8b-instant).
    ai_image_prompt = await extract_ai_image_prompt(
        voiced_text=voiced, prompt_id=prompt.id
    )
    extracts["ai_image_prompt"] = ai_image_prompt

    return hook, body, tags, extracts, violations


async def compress_for_bluesky(
    *, source_text: str, prompt_id: UUID | None = None
) -> str:
    """Rewrite a LinkedIn-shaped post for Bluesky's 300-char cap.

    FAST model + tight system prompt. Falls back to a brand-safe one-liner
    when the rewrite is empty or still over the cap — better to ship a
    publishable Bluesky post than a 1641-char one that fails at publish.
    """
    raw = await groq_client.chat(
        stage="bluesky_compress",
        model=settings.GROQ_MODEL_FAST,
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


async def _build_platform_commentary(
    platform: Platform, *, source_text: str, prompt_id: UUID | None = None
) -> str | None:
    """Per-platform rewrite. LinkedIn uses the canonical Post body (returns
    None — orchestrator assembles from hook/body/tags). Bluesky always goes
    through the 300-char compression — Stage 2 hardcodes the LinkedIn voice
    prompt so even a Bluesky-only draft has a 1000+ char Post.body, and the
    orchestrator's char-limit gate would fail without a compressed override
    on the target. Mastodon/Threads/Instagram: TODO until publishers land."""
    if platform == Platform.linkedin:
        return None
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

    prompt = await _load_active_prompt(session, category)

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
