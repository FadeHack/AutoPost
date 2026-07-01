"""Tests for the rendering layer.

Pure-unit only — no real Chromium, no real DB. `playwright_runner.html_to_png`
is monkeypatched out; `_pick_template` is exercised against a mocked
AsyncSession. The full end-to-end loop (Playwright + Supabase) is verified
manually via the smoke script in CHECKLIST / CONTEXT, not in CI.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.config import settings
from app.models.base import PostCategory
from app.rendering import renderer


# ---- fixtures ---------------------------------------------------------------


def _make_post(
    *,
    category: PostCategory = PostCategory.founder_insight,
    hook: str = "Hiring by tenure ignores evidence of work.",
    body: str = "Body paragraph one.\n\nBody paragraph two.",
    tags: list[str] | None = None,
    extracts: dict | None = None,
) -> SimpleNamespace:
    """Lightweight Post stand-in for renderer tests. Mirrors the attrs renderer reads."""
    return SimpleNamespace(
        id=uuid4(),
        category=category,
        hook=hook,
        body=body,
        tags=tags if tags is not None else ["founders", "hiring"],
        extracts=extracts,
    )


# ---- default_template_name_for_post ----------------------------------------


class TestDefaultTemplateName:
    def test_every_post_category_has_a_default(self):
        for cat in PostCategory:
            post = _make_post(category=cat)
            name = renderer.default_template_name_for_post(post)
            assert name, f"{cat} returned empty template name"
            # Default name must point to an existing on-disk template file.
            assert (renderer.TEMPLATES_DIR / f"{name}.html").exists(), (
                f"default for {cat} is '{name}' but file does not exist"
            )

    def test_carousel_post_maps_to_carousel_slide(self):
        post = _make_post(category=PostCategory.carousel)
        assert renderer.default_template_name_for_post(post) == "carousel_slide"

    def test_ai_automation_with_metric_maps_to_metric_card(self):
        post = _make_post(
            category=PostCategory.ai_automation,
            extracts={
                "pull_quote": None,
                "metric_value": "$2,180/mo",
                "metric_label": "API spend",
                "carousel_slides": [],
            },
        )
        assert renderer.default_template_name_for_post(post) == "metric_card"

    def test_ai_automation_without_metric_falls_back_to_insight(self):
        # Smart fallback: long hooks overflow metric_card if there's no real
        # metric to feature, so auto-pick uses insight_card instead.
        post = _make_post(category=PostCategory.ai_automation, extracts=None)
        assert renderer.default_template_name_for_post(post) == "insight_card"

    def test_ai_automation_with_null_metric_falls_back_to_insight(self):
        post = _make_post(
            category=PostCategory.ai_automation,
            extracts={
                "pull_quote": "x",
                "metric_value": None,
                "metric_label": None,
                "carousel_slides": [],
            },
        )
        assert renderer.default_template_name_for_post(post) == "insight_card"


# ---- default_context_for_post ----------------------------------------------


class TestDefaultContext:
    def test_returns_required_keys(self):
        post = _make_post()
        ctx = renderer.default_context_for_post(post)
        assert set(ctx) >= {"hook", "body", "tags", "brand_name", "category_label"}

    def test_uses_brand_name_setting(self):
        post = _make_post()
        ctx = renderer.default_context_for_post(post)
        assert ctx["brand_name"] == settings.BRAND_NAME

    def test_category_label_is_human_readable(self):
        post = _make_post(category=PostCategory.ai_automation)
        ctx = renderer.default_context_for_post(post)
        assert ctx["category_label"] == "AI · Automation"

    def test_empty_tags_become_empty_list(self):
        post = _make_post()
        post.tags = None  # mimic a freshly-created Post before defaults applied
        ctx = renderer.default_context_for_post(post)
        assert ctx["tags"] == []


class TestExtractsInContext:
    """default_context_for_post pulls pull_quote / metric / slides from extracts."""

    def test_pull_quote_falls_back_to_hook_when_extracts_none(self):
        post = _make_post(extracts=None, hook="Use the hook then.")
        ctx = renderer.default_context_for_post(post)
        assert ctx["pull_quote"] == "Use the hook then."

    def test_pull_quote_from_extracts_when_present(self):
        post = _make_post(
            hook="Hook",
            extracts={
                "pull_quote": "A punchier pulled line.",
                "metric_value": None,
                "metric_label": None,
                "carousel_slides": [],
            },
        )
        ctx = renderer.default_context_for_post(post)
        assert ctx["pull_quote"] == "A punchier pulled line."

    def test_metric_fields_passthrough(self):
        post = _make_post(
            extracts={
                "pull_quote": "x",
                "metric_value": "$2,180/mo",
                "metric_label": "API spend",
                "carousel_slides": [],
            }
        )
        ctx = renderer.default_context_for_post(post)
        assert ctx["metric_value"] == "$2,180/mo"
        assert ctx["metric_label"] == "API spend"

    def test_no_extracts_falls_back_to_single_slide_of_hook(self):
        post = _make_post(hook="Solo hook.", extracts=None)
        ctx = renderer.default_context_for_post(post)
        assert ctx["slide_text"] == "Solo hook."
        assert ctx["slide_number"] == 1
        assert ctx["slide_total"] == 1

    def test_slide_index_picks_the_right_slide(self):
        post = _make_post(
            extracts={
                "pull_quote": None,
                "metric_value": None,
                "metric_label": None,
                "carousel_slides": [
                    {"text": "Slide 1"},
                    {"text": "Slide 2"},
                    {"text": "Slide 3"},
                ],
            }
        )
        ctx = renderer.default_context_for_post(post, slide_index=2)
        assert ctx["slide_text"] == "Slide 2"
        assert ctx["slide_number"] == 2
        assert ctx["slide_total"] == 3

    def test_slide_index_clamps_above_total(self):
        post = _make_post(
            extracts={
                "pull_quote": None,
                "metric_value": None,
                "metric_label": None,
                "carousel_slides": [{"text": "Only"}],
            }
        )
        ctx = renderer.default_context_for_post(post, slide_index=99)
        assert ctx["slide_text"] == "Only"
        assert ctx["slide_number"] == 1

    def test_slide_index_clamps_below_one(self):
        post = _make_post(
            extracts={
                "pull_quote": None,
                "metric_value": None,
                "metric_label": None,
                "carousel_slides": [{"text": "A"}, {"text": "B"}],
            }
        )
        ctx = renderer.default_context_for_post(post, slide_index=0)
        assert ctx["slide_number"] == 1
        assert ctx["slide_text"] == "A"


# ---- render_html (Jinja2, no browser) --------------------------------------


class TestRenderHtml:
    @pytest.mark.parametrize(
        "template_name",
        ["insight_card.html", "quote_card.html", "metric_card.html", "carousel_slide.html"],
    )
    def test_each_template_renders(self, template_name: str):
        post = _make_post()
        ctx = renderer.default_context_for_post(post)
        # carousel reads two extra optional vars; the |default filter handles them.
        html = renderer.render_html(template_name, ctx)
        assert html.startswith("<!DOCTYPE html>")
        assert post.hook in html
        assert settings.BRAND_NAME in html

    def test_html_escapes_user_content(self):
        post = _make_post(hook='Drop <script>alert("xss")</script> in the hook.')
        ctx = renderer.default_context_for_post(post)
        html = renderer.render_html("insight_card.html", ctx)
        # autoescape must turn the angle brackets into entities.
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_metric_card_uses_metric_branch_when_value_present(self):
        # Hook is always echoed in <title>, so the test proves the *branch* fired
        # via the unique class signature, not via hook-absence.
        post = _make_post(
            extracts={
                "pull_quote": None,
                "metric_value": "$2,180/mo",
                "metric_label": "monthly Claude API spend",
                "carousel_slides": [],
            },
        )
        ctx = renderer.default_context_for_post(post)
        html = renderer.render_html("metric_card.html", ctx)
        assert "$2,180/mo" in html
        assert "monthly Claude API spend" in html
        # Metric branch uses text-[160px]; fallback uses text-[112px].
        assert "text-[160px]" in html
        assert "text-[112px]" not in html

    def test_metric_card_falls_back_to_hook_when_no_metric(self):
        post = _make_post(hook="The hook is the headline now.")
        ctx = renderer.default_context_for_post(post)
        html = renderer.render_html("metric_card.html", ctx)
        # Fallback branch uses text-[64px]; metric branch uses text-[160px].
        # The fallback is shrunk vs. the metric branch so long hooks fit.
        assert "text-[64px]" in html
        assert "text-[160px]" not in html
        assert "The hook is the headline now." in html

    def test_quote_card_uses_pull_quote_over_hook(self):
        post = _make_post(
            extracts={
                "pull_quote": "A genuinely better pulled line.",
                "metric_value": None,
                "metric_label": None,
                "carousel_slides": [],
            },
        )
        ctx = renderer.default_context_for_post(post)
        html = renderer.render_html("quote_card.html", ctx)
        # pull_quote is in the centerpiece <h1>, not just the <title>.
        assert "A genuinely better pulled line." in html
        # The <h1> tag should contain the pull quote.
        assert "<h1" in html
        h1_block = html[html.index("<h1") : html.index("</h1>")]
        assert "A genuinely better pulled line." in h1_block

    def test_carousel_slide_uses_slide_text(self):
        post = _make_post(
            extracts={
                "pull_quote": None,
                "metric_value": None,
                "metric_label": None,
                "carousel_slides": [
                    {"text": "slide one specific text"},
                    {"text": "slide two specific text"},
                ],
            },
        )
        ctx = renderer.default_context_for_post(post, slide_index=2)
        html = renderer.render_html("carousel_slide.html", ctx)
        assert "slide two specific text" in html
        # Slide indicator shows correct fraction.
        assert "2 / 2" in html
        # Centerpiece <h1> renders the slide text.
        h1_block = html[html.index("<h1") : html.index("</h1>")]
        assert "slide two specific text" in h1_block


# ---- render_png (Jinja2 + monkeypatched Playwright) ------------------------


class TestRenderPng:
    @pytest.mark.asyncio
    async def test_calls_playwright_with_rendered_html_and_dimensions(
        self, monkeypatch
    ):
        captured: dict = {}

        async def fake_html_to_png(html: str, *, width: int, height: int, **kw) -> bytes:
            captured["html"] = html
            captured["width"] = width
            captured["height"] = height
            return b"\x89PNG\r\n\x1a\n-stub-"

        monkeypatch.setattr(
            "app.rendering.playwright_runner.html_to_png", fake_html_to_png
        )

        post = _make_post(hook="Specific test hook 8a3f.")
        ctx = renderer.default_context_for_post(post)
        png = await renderer.render_png("insight_card.html", ctx, width=800, height=900)

        assert png == b"\x89PNG\r\n\x1a\n-stub-"
        assert captured["width"] == 800
        assert captured["height"] == 900
        assert "Specific test hook 8a3f" in captured["html"]


# ---- _pick_template (mocked AsyncSession) ----------------------------------


class TestPickTemplate:
    @pytest.mark.asyncio
    async def test_explicit_template_id_loads_by_id(self):
        session = MagicMock()
        wanted = SimpleNamespace(id=uuid4(), name="quote_card")
        session.get = AsyncMock(return_value=wanted)

        post = _make_post()
        result = await renderer._pick_template(session, post, template_id=wanted.id)

        assert result is wanted
        session.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_without_id_loads_default_by_name(self):
        post = _make_post(category=PostCategory.founder_insight)
        default_template = SimpleNamespace(
            id=uuid4(), name="insight_card", html_path="insight_card.html"
        )

        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = default_template
        session = MagicMock()
        session.execute = AsyncMock(return_value=scalar_result)

        result = await renderer._pick_template(session, post, template_id=None)
        assert result is default_template
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_when_explicit_id_not_found(self):
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        post = _make_post()
        with pytest.raises(ValueError, match="not found"):
            await renderer._pick_template(session, post, template_id=uuid4())

    @pytest.mark.asyncio
    async def test_raises_when_default_not_seeded(self):
        post = _make_post(category=PostCategory.founder_insight)
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        session = MagicMock()
        session.execute = AsyncMock(return_value=scalar_result)

        with pytest.raises(ValueError, match="not seeded"):
            await renderer._pick_template(session, post, template_id=None)


class TestAIImageWrapTemplate:
    """Pure-Jinja2 render of the brand-wrap template (no Playwright)."""

    def test_renders_with_data_uri_and_brand(self):
        from app.rendering.renderer import render_html

        data_uri = "data:image/png;base64,AAAA"
        out = render_html(
            "ai_image_wrap.html",
            {
                "hook": "A sharp hook line",
                "brand_name": "Nestwhirr",
                "category_label": "Founder insight",
                "image_data_uri": data_uri,
            },
        )
        assert data_uri in out
        assert "Nestwhirr" in out
        assert "Founder insight" in out

    def test_escapes_hook_in_title(self):
        from app.rendering.renderer import render_html

        out = render_html(
            "ai_image_wrap.html",
            {
                "hook": "<script>x</script>",
                "brand_name": "B",
                "category_label": "C",
                "image_data_uri": "data:image/png;base64,A",
            },
        )
        # Jinja2 autoescape is on for html → tags become entities.
        assert "<script>" not in out
        assert "&lt;script&gt;" in out


class TestAIImageBareTemplate:
    """Full-bleed (no-brand-frame) AI-image template — pure Jinja2."""

    def test_renders_full_bleed_without_brand_chrome(self):
        from app.rendering.renderer import render_html

        data_uri = "data:image/png;base64,AAAA"
        out = render_html("ai_image_bare.html", {"hook": "h", "image_data_uri": data_uri})

        assert data_uri in out
        # Full-bleed 1200x1200, no brand strap / eyebrow text.
        assert "1200px" in out
        assert "Nestwhirr" not in out


class TestAIImageMarkTemplate:
    """Lighter-touch frame: full-bleed image + small corner brand mark."""

    def test_renders_full_bleed_with_brand_mark(self):
        from app.rendering.renderer import render_html

        data_uri = "data:image/png;base64,AAAA"
        out = render_html(
            "ai_image_mark.html",
            {"hook": "h", "brand_name": "Nestwhirr", "image_data_uri": data_uri},
        )

        assert data_uri in out
        assert "1200px" in out  # full-bleed
        assert "Nestwhirr" in out  # brand mark present


class TestRenderAIImageTemplateSelection:
    """`_render_ai_image` picks the template off the `frame` value."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "frame, expected_name",
        [
            ("card", "ai_image_wrap"),
            ("mark", "ai_image_mark"),
            ("none", "ai_image_bare"),
            ("bogus", "ai_image_wrap"),  # unknown → default card
        ],
    )
    async def test_frame_selects_template(self, monkeypatch, frame, expected_name):
        loaded: dict = {}

        async def fake_ensure_prompt(session, post):
            return "a stone on a table"

        async def fake_generate_image(prompt):
            return b"\x89PNG-stub"

        async def fake_load_by_name(session, name):
            loaded["name"] = name
            return SimpleNamespace(id=uuid4(), name=name, html_path=f"{name}.html")

        async def fake_render_png(html_path, context, *, width, height, **kw):
            loaded["image_format"] = kw.get("image_format", "png")
            return b"final-img"

        async def fake_upload(rel_path, data, **kw):
            loaded["upload_path"] = rel_path
            loaded["content_type"] = kw.get("content_type", "image/png")
            return None

        monkeypatch.setattr(renderer, "_ensure_ai_image_prompt", fake_ensure_prompt)
        monkeypatch.setattr(renderer, "generate_image", fake_generate_image)
        monkeypatch.setattr(renderer, "_load_template_by_name", fake_load_by_name)
        monkeypatch.setattr(renderer, "render_png", fake_render_png)
        monkeypatch.setattr(renderer.storage, "upload_image", fake_upload)

        session = MagicMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        post = _make_post(extracts={"ai_image_prompt": "x"})
        await renderer._render_ai_image(
            session, post, template_id=None, width=1200, height=1200, frame=frame
        )

        assert loaded["name"] == expected_name
        # AI images are always encoded/stored as JPEG regardless of frame.
        assert loaded["image_format"] == "jpeg"
        assert loaded["content_type"] == "image/jpeg"
        assert loaded["upload_path"].endswith(".jpg")
