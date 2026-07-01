"""Unit tests for generator helpers and the LLM-only pipeline.

The pipeline is tested without DB. `groq_client.chat` is monkeypatched to
return stage-specific canned responses; we assert the right messages, models,
and stage labels flow through.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.config import settings
from app.intelligence import generator
from app.models.base import PostCategory


def _fake_prompt(category: PostCategory = PostCategory.founder_insight):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=category.value,
        category=category,
        body="<system prompt for testing>",
        version=1,
        is_active=True,
    )


def _fake_trend(title="Some title", summary="Some summary", url="https://ex.com/a"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        title=title,
        url=url,
        summary=summary,
    )


class TestParseExtract:
    def test_well_formed_json(self):
        raw = '{"hook": "Hello world", "body": "Body content here.", "tags": ["ai", "startups"]}'
        hook, body, tags = generator._parse_extract(raw, fallback_body="fallback")
        assert hook == "Hello world"
        assert body == "Body content here."
        assert tags == ["ai", "startups"]

    def test_strips_duplicate_hook_from_body(self):
        raw = '{"hook": "Top line.", "body": "Top line.\\n\\nRest of body.", "tags": []}'
        hook, body, _ = generator._parse_extract(raw, fallback_body="fallback")
        assert hook == "Top line."
        assert body == "Rest of body."

    def test_strips_trailing_hashtag_line_from_body(self):
        raw = '{"hook": "H", "body": "Real body.\\n\\n#ai #startups", "tags": ["ai", "startups"]}'
        _, body, _ = generator._parse_extract(raw, fallback_body="x")
        assert body == "Real body."

    def test_bad_json_falls_back_to_first_line(self):
        raw = "this is not json"
        fallback = "First line of post.\n\nRest of body."
        hook, body, tags = generator._parse_extract(raw, fallback_body=fallback)
        assert hook == "First line of post."
        assert body == fallback
        assert tags == []

    def test_strips_hash_from_tags_and_lowercases(self):
        raw = '{"hook":"h","body":"b","tags":["#AI","#StartUps","#tech"]}'
        _, _, tags = generator._parse_extract(raw, fallback_body="x")
        assert tags == ["ai", "startups", "tech"]

    def test_caps_tags_at_three(self):
        raw = '{"hook":"h","body":"b","tags":["a","b","c","d","e"]}'
        _, _, tags = generator._parse_extract(raw, fallback_body="x")
        assert tags == ["a", "b", "c"]

    def test_dedupes_tags(self):
        raw = '{"hook":"h","body":"b","tags":["AI","ai","AI"]}'
        _, _, tags = generator._parse_extract(raw, fallback_body="x")
        assert tags == ["ai"]

    def test_non_list_tags_becomes_empty(self):
        raw = '{"hook":"h","body":"b","tags":"not-a-list"}'
        _, _, tags = generator._parse_extract(raw, fallback_body="x")
        assert tags == []

    def test_missing_hook_takes_first_line_of_body(self):
        # When hook is missing, it's reconstructed from body's first line, then
        # that duplicate line is stripped from body. Net: body = remainder.
        raw = '{"body": "Real first line.\\nrest"}'
        hook, body, _ = generator._parse_extract(raw, fallback_body="x")
        assert hook == "Real first line."
        assert body == "rest"


class TestFormatTrend:
    def test_includes_title_url_summary_body(self):
        t = _fake_trend(title="T", summary="S", url="https://example.com/x")
        out = generator._format_trend(t, "the article body here")
        assert "Title: T" in out
        assert "URL: https://example.com/x" in out
        assert "Summary: S" in out
        assert "the article body here" in out

    def test_omits_summary_when_none(self):
        t = SimpleNamespace(title="T", url="u", summary=None)
        out = generator._format_trend(t, None)
        assert "Summary" not in out
        assert "Article body" not in out

    def test_truncates_long_summary(self):
        long = "x" * (generator.TRUNCATE_SUMMARY + 1000)
        t = SimpleNamespace(title="T", url="u", summary=long)
        out = generator._format_trend(t, None)
        # Summary line plus the two header lines — overall length bounded by truncate cap.
        summary_line = next(l for l in out.split("\n") if l.startswith("Summary:"))
        assert len(summary_line) <= generator.TRUNCATE_SUMMARY + len("Summary: ")


_GOOD_VISUAL_EXTRACT = (
    '{"pull_quote":"The signal that matters is evidence of work.",'
    '"metric_value":"47%",'
    '"metric_label":"of teams skip evidence",'
    '"carousel_slides":['
    '{"text":"Hook line"},'
    '{"text":"Middle beat"},'
    '{"text":"Takeaway"}'
    "]}"
)

_GOOD_AI_IMAGE_PROMPT = (
    '{"ai_image_prompt":"a single empty coffee cup on a dark wooden desk, '
    'soft side light, minimal editorial"}'
)


class TestRunPipeline:
    async def test_full_five_stage_flow(self, monkeypatch):
        calls: list[dict] = []

        responses = {
            "angle": "Raw angle output — has an em-dash separator.",
            "voice": (
                "Sharp hook line.\n\n"
                "A real concrete detail with a 47% number.\n\n"
                "Reframed takeaway."
            ),
            "extract": (
                '{"hook":"Sharp hook line.",'
                '"body":"Sharp hook line.\\n\\nA real concrete detail with a 47% number.\\n\\nReframed takeaway.",'
                '"tags":["builders","ai"]}'
            ),
            "visual_extract": _GOOD_VISUAL_EXTRACT,
            "ai_image_prompt": _GOOD_AI_IMAGE_PROMPT,
        }

        async def fake_chat(**kwargs):
            calls.append(kwargs)
            return responses[kwargs["stage"]]

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)

        prompt = _fake_prompt()
        hook, body, tags, extracts, violations = await generator.run_pipeline(
            prompt=prompt,
            trends_block="Title: X\nURL: https://x.com\nSummary: y",
        )

        # 5 stages, in order, with the right models.
        assert [c["stage"] for c in calls] == [
            "angle",
            "voice",
            "extract",
            "visual_extract",
            "ai_image_prompt",
        ]
        assert calls[0]["model"] == settings.GROQ_MODEL_PRIMARY
        assert calls[1]["model"] == settings.GROQ_MODEL_PRIMARY
        assert calls[2]["model"] == settings.GROQ_MODEL_FAST
        assert calls[3]["model"] == settings.GROQ_MODEL_FAST
        assert calls[4]["model"] == settings.GROQ_MODEL_PRIMARY  # Stage 5 image prompt

        # prompt_id propagated to every call.
        assert all(c["prompt_id"] == prompt.id for c in calls)

        # Stage 1's system message is the prompt body.
        assert calls[0]["messages"][0]["content"] == prompt.body

        # Stages 3, 4, 5 all use JSON response_format.
        assert calls[2]["response_format"] == {"type": "json_object"}
        assert calls[3]["response_format"] == {"type": "json_object"}
        assert calls[4]["response_format"] == {"type": "json_object"}

        assert hook == "Sharp hook line."
        assert "47%" in body
        assert tags == ["builders", "ai"]

        # Stage 4 output flows through to extracts.
        assert extracts["pull_quote"] == "The signal that matters is evidence of work."
        assert extracts["metric_value"] == "47%"
        assert extracts["metric_label"] == "of teams skip evidence"
        assert len(extracts["carousel_slides"]) == 3

        # Stage 5 output landed on the same extracts dict.
        assert "coffee cup" in extracts["ai_image_prompt"]

    async def test_voice_strip_runs_between_stage_2_and_3(self, monkeypatch):
        captured_extract_input: list[str] = []

        async def fake_chat(**kwargs):
            stage = kwargs["stage"]
            if stage == "angle":
                return "angle output"
            if stage == "voice":
                # Stage 2 output deliberately contains an em-dash separator
                # and a banned phrase. Strip should clean both before extract.
                return "Hook line — with em-dash. Moreover, this is bad."
            if stage == "polish":
                # ≥2 violations escalates to fast-model polish; return as-is.
                return kwargs["messages"][1]["content"]
            if stage == "extract":
                # Capture what extract received — that's the post-strip text.
                captured_extract_input.append(kwargs["messages"][1]["content"])
                return '{"hook":"Hook line.","body":"Hook line. with em-dash. this is bad.","tags":[]}'
            if stage == "visual_extract":
                return _GOOD_VISUAL_EXTRACT
            if stage == "ai_image_prompt":
                return _GOOD_AI_IMAGE_PROMPT
            raise AssertionError(f"unexpected stage {stage}")

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)

        _, _, _, _, violations = await generator.run_pipeline(
            prompt=_fake_prompt(), trends_block="x"
        )

        assert "em_dash_separator" in violations
        assert "moreover" in violations
        # The text passed to Stage 3 had the em-dash and banned phrase stripped.
        assert "—" not in captured_extract_input[0]
        assert "moreover" not in captured_extract_input[0].lower()

    async def test_polish_escalates_only_above_threshold(self, monkeypatch):
        """One violation → no polish. Two+ → polish stage runs."""
        stages_seen: list[str] = []

        async def fake_chat(**kwargs):
            stage = kwargs["stage"]
            stages_seen.append(stage)
            if stage == "voice":
                # Exactly ONE violation (em-dash only) — below threshold.
                return "Hook line — with em-dash. Clean otherwise."
            if stage == "polish":
                return kwargs["messages"][1]["content"]
            if stage == "extract":
                return '{"hook":"Hook.","body":"Body.","tags":[]}'
            if stage == "visual_extract":
                return _GOOD_VISUAL_EXTRACT
            if stage == "ai_image_prompt":
                return _GOOD_AI_IMAGE_PROMPT
            return "x"

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)
        await generator.run_pipeline(prompt=_fake_prompt(), trends_block="x")
        assert "polish" not in stages_seen

        stages_seen.clear()

        async def fake_chat_two(**kwargs):
            stage = kwargs["stage"]
            stages_seen.append(stage)
            if stage == "voice":
                # Two violations — em-dash + banned phrase. Escalates.
                return "Hook — with em-dash. Moreover, more text."
            if stage == "polish":
                return "polished output."
            if stage == "extract":
                return '{"hook":"Hook.","body":"Body.","tags":[]}'
            if stage == "visual_extract":
                return _GOOD_VISUAL_EXTRACT
            if stage == "ai_image_prompt":
                return _GOOD_AI_IMAGE_PROMPT
            return "x"

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat_two)
        await generator.run_pipeline(prompt=_fake_prompt(), trends_block="x")
        assert "polish" in stages_seen

    async def test_bad_json_from_extract_falls_back(self, monkeypatch):
        async def fake_chat(**kwargs):
            stage = kwargs["stage"]
            if stage == "extract":
                return "not json at all"
            if stage == "visual_extract":
                return _GOOD_VISUAL_EXTRACT
            if stage == "ai_image_prompt":
                return _GOOD_AI_IMAGE_PROMPT
            return "Sharp hook line.\n\nBody paragraph.\n\nTakeaway."

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)

        hook, body, tags, _extracts, _ = await generator.run_pipeline(
            prompt=_fake_prompt(), trends_block="x"
        )

        assert hook == "Sharp hook line."
        assert body.startswith("Sharp hook line.")
        assert tags == []


class TestParseVisualExtract:
    def test_well_formed_json(self):
        out = generator._parse_visual_extract(_GOOD_VISUAL_EXTRACT)
        assert out["pull_quote"] == "The signal that matters is evidence of work."
        assert out["metric_value"] == "47%"
        assert out["metric_label"] == "of teams skip evidence"
        assert [s["text"] for s in out["carousel_slides"]] == [
            "Hook line",
            "Middle beat",
            "Takeaway",
        ]

    def test_bad_json_returns_empty(self):
        out = generator._parse_visual_extract("not json at all")
        assert out == generator.empty_extracts()

    def test_non_dict_json_returns_empty(self):
        out = generator._parse_visual_extract("[1, 2, 3]")
        assert out == generator.empty_extracts()

    def test_missing_metric_label_drops_metric_value(self):
        raw = '{"pull_quote":"x","metric_value":"$1k","metric_label":null,"carousel_slides":[]}'
        out = generator._parse_visual_extract(raw)
        # Co-required — both go.
        assert out["metric_value"] is None
        assert out["metric_label"] is None

    def test_missing_metric_value_drops_metric_label(self):
        raw = '{"metric_value":null,"metric_label":"context only","carousel_slides":[]}'
        out = generator._parse_visual_extract(raw)
        assert out["metric_value"] is None
        assert out["metric_label"] is None

    def test_caps_slides_at_max(self):
        slides = ",".join(
            f'{{"text":"slide {i}"}}' for i in range(generator.MAX_CAROUSEL_SLIDES + 5)
        )
        raw = '{"carousel_slides":[' + slides + "]}"
        out = generator._parse_visual_extract(raw)
        assert len(out["carousel_slides"]) == generator.MAX_CAROUSEL_SLIDES

    def test_tolerates_bare_string_slides(self):
        raw = '{"carousel_slides":["just a string", "another"]}'
        out = generator._parse_visual_extract(raw)
        assert [s["text"] for s in out["carousel_slides"]] == [
            "just a string",
            "another",
        ]

    def test_empty_pull_quote_becomes_none(self):
        raw = '{"pull_quote":"   ","carousel_slides":[]}'
        out = generator._parse_visual_extract(raw)
        assert out["pull_quote"] is None

    def test_empty_extracts_shape(self):
        empty = generator.empty_extracts()
        assert empty == {
            "pull_quote": None,
            "metric_value": None,
            "metric_label": None,
            "carousel_slides": [],
        }


class TestExtractVisualFields:
    async def test_calls_fast_model_with_json_format(self, monkeypatch):
        calls: list[dict] = []

        async def fake_chat(**kwargs):
            calls.append(kwargs)
            return _GOOD_VISUAL_EXTRACT

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)

        result = await generator.extract_visual_fields(voiced_text="some post")

        assert len(calls) == 1
        assert calls[0]["stage"] == "visual_extract"
        assert calls[0]["model"] == settings.GROQ_MODEL_FAST
        assert calls[0]["response_format"] == {"type": "json_object"}
        assert calls[0]["messages"][1]["content"] == "some post"
        assert result["pull_quote"] == "The signal that matters is evidence of work."


class TestParseAIImagePrompt:
    def test_well_formed_json_returns_prompt(self):
        out = generator._parse_ai_image_prompt(_GOOD_AI_IMAGE_PROMPT)
        assert out is not None
        assert "coffee cup" in out

    def test_bad_json_returns_none(self):
        assert generator._parse_ai_image_prompt("not json at all") is None

    def test_non_dict_top_level_returns_none(self):
        assert generator._parse_ai_image_prompt('["array","not","dict"]') is None

    def test_missing_key_returns_none(self):
        assert generator._parse_ai_image_prompt('{"other_field": "x"}') is None

    def test_empty_string_returns_none(self):
        assert generator._parse_ai_image_prompt('{"ai_image_prompt": ""}') is None

    def test_whitespace_only_returns_none(self):
        assert generator._parse_ai_image_prompt('{"ai_image_prompt": "   "}') is None


class TestExtractAIImagePrompt:
    async def test_happy_path_returns_parsed_string(self, monkeypatch):
        calls: list[dict] = []

        async def fake_chat(**kwargs):
            calls.append(kwargs)
            return _GOOD_AI_IMAGE_PROMPT

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)

        out = await generator.extract_ai_image_prompt(voiced_text="some post body")

        assert len(calls) == 1
        assert calls[0]["stage"] == "ai_image_prompt"
        assert calls[0]["model"] == settings.GROQ_MODEL_PRIMARY
        assert calls[0]["response_format"] == {"type": "json_object"}
        assert calls[0]["messages"][1]["content"] == "some post body"
        assert "coffee cup" in out

    async def test_bad_json_returns_brand_fallback(self, monkeypatch):
        async def fake_chat(**kwargs):
            return "not json"

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)
        out = await generator.extract_ai_image_prompt(voiced_text="x")
        # Fallback string is non-empty and contains brand-safe terms.
        assert out == generator._AI_IMAGE_PROMPT_FALLBACK
        assert out.strip() != ""

    async def test_empty_prompt_returns_brand_fallback(self, monkeypatch):
        async def fake_chat(**kwargs):
            return '{"ai_image_prompt": ""}'

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)
        out = await generator.extract_ai_image_prompt(voiced_text="x")
        assert out == generator._AI_IMAGE_PROMPT_FALLBACK


# ---------------------------------------------------------------------------
# Phase 11 Chunk A follow-up — per-platform commentary
# ---------------------------------------------------------------------------


from app.models.base import Platform  # noqa: E402


class TestCanonicalPlatform:
    """LinkedIn always wins when selected; otherwise platforms are ranked by
    a fixed order so the canonical Post body is deterministic across calls."""

    def test_linkedin_always_canonical_when_present(self):
        assert (
            generator._canonical_platform([Platform.bluesky, Platform.linkedin])
            == Platform.linkedin
        )

    def test_bluesky_only_returns_bluesky(self):
        assert generator._canonical_platform([Platform.bluesky]) == Platform.bluesky

    def test_empty_falls_back_to_linkedin(self):
        assert generator._canonical_platform([]) == Platform.linkedin


class TestCompressForBluesky:
    async def test_happy_path_returns_compressed(self, monkeypatch):
        async def fake_chat(**_kwargs):
            return "Hot take. One line of support. #ai"

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)
        out = await generator.compress_for_bluesky(source_text="long source post" * 100)
        assert out == "Hot take. One line of support. #ai"
        assert len(out) <= 300

    async def test_empty_response_falls_back_to_brand_safe(self, monkeypatch):
        async def fake_chat(**_kwargs):
            return ""

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)
        out = await generator.compress_for_bluesky(source_text="src")
        assert out == generator._BLUESKY_FALLBACK_COMMENTARY

    async def test_over_300_chars_falls_back_to_brand_safe(self, monkeypatch):
        async def fake_chat(**_kwargs):
            # Model returned something but it's still way too long — orchestrator
            # would fail the gate, so we'd rather ship the safe one-liner.
            return "x" * 350

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)
        out = await generator.compress_for_bluesky(source_text="src")
        assert out == generator._BLUESKY_FALLBACK_COMMENTARY

    async def test_strips_wrapping_quotes(self, monkeypatch):
        async def fake_chat(**_kwargs):
            return '"Hot take. Short body."'

        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)
        out = await generator.compress_for_bluesky(source_text="src")
        assert out == "Hot take. Short body."


class TestBuildPlatformCommentary:
    async def test_linkedin_returns_none(self):
        # Canonical platform leaves PostTarget.commentary NULL so the
        # orchestrator falls back to the Post hook+body+tags assemble. LinkedIn
        # short-circuits before any DB lookup, so session=None is safe.
        out = await generator._build_platform_commentary(
            None,
            PostCategory.founder_insight,
            Platform.linkedin,
            source_text="anything",
        )
        assert out is None

    async def test_bluesky_no_prompt_falls_back_to_compress(self, monkeypatch):
        # No per-platform Bluesky prompt seeded for this category → legacy
        # compress_for_bluesky keeps existing categories publishing.
        async def no_prompt(*_a, **_k):
            return None

        async def fake_chat(**_kwargs):
            return "Short."

        monkeypatch.setattr(generator, "_load_platform_prompt", no_prompt)
        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)
        out = await generator._build_platform_commentary(
            None,
            PostCategory.founder_insight,
            Platform.bluesky,
            source_text="long source",
        )
        assert out == "Short."

    async def test_uses_db_prompt_when_present(self, monkeypatch):
        # A seeded per-platform prompt drives a proper Stage-2 rewrite instead
        # of the compress fallback.
        fake_prompt = SimpleNamespace(
            id=uuid.uuid4(), platform=Platform.bluesky, body="bluesky voice"
        )

        async def has_prompt(*_a, **_k):
            return fake_prompt

        async def fake_chat(**_kwargs):
            return "Rewritten for bluesky."

        monkeypatch.setattr(generator, "_load_platform_prompt", has_prompt)
        monkeypatch.setattr(generator.groq_client, "chat", fake_chat)
        out = await generator._build_platform_commentary(
            None,
            PostCategory.founder_insight,
            Platform.bluesky,
            source_text="long source",
        )
        assert out == "Rewritten for bluesky."

    async def test_mastodon_no_prompt_returns_none(self, monkeypatch):
        # No per-platform prompt + not Bluesky → None (falls back to canonical
        # Post.body and trips the char-limit gate loudly).
        async def no_prompt(*_a, **_k):
            return None

        monkeypatch.setattr(generator, "_load_platform_prompt", no_prompt)
        out = await generator._build_platform_commentary(
            None,
            PostCategory.founder_insight,
            Platform.mastodon,
            source_text="long source",
        )
        assert out is None


# Orchestrator build_commentary with per-target commentary
from app.publishing import orchestrator as _orch  # noqa: E402


def test_build_commentary_uses_target_commentary_when_set():
    post = SimpleNamespace(
        hook="Long hook",
        body="Long body" * 100,
        tags=["ai", "founders"],
    )
    target = SimpleNamespace(commentary="Compressed Bluesky line.")
    out = _orch.build_commentary(post, target)
    assert out == "Compressed Bluesky line."


def test_build_commentary_falls_back_when_target_commentary_null():
    post = SimpleNamespace(
        hook="Hook.",
        body="Body.",
        tags=["x"],
    )
    target = SimpleNamespace(commentary=None)
    out = _orch.build_commentary(post, target)
    assert "Hook." in out and "Body." in out and "#x" in out


def test_build_commentary_no_target_falls_back():
    post = SimpleNamespace(hook="Hook.", body="Body.", tags=[])
    out = _orch.build_commentary(post, None)
    assert out.startswith("Hook.")
