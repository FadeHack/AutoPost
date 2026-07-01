"""Render a Post to a PNG visual via a Jinja2-templated HTML file + Playwright.

Two layers:
  - `render_html(name, ctx)` and `render_png(name, ctx, w, h)` are *pure* —
    no DB, no storage write. They're the testable seam.
  - `render_post(session, post_id, template_id?, slide_index?)` is the DB
    orchestration: load Post, lazily Stage-4-extract if needed, pick Template,
    render PNG bytes, upload to Supabase Storage, persist GeneratedAsset row.

Default template picker maps `PostCategory → template name`. Caller can override
with an explicit `template_id`. For `carousel_slide` templates, `slide_index`
(1-based) picks which slide from `post.extracts.carousel_slides` to render.

Per-template content (pull-quote / metric / slides) lives on `post.extracts`
(Stage 4 output, JSONB). Posts predating Stage 4 have `extracts=NULL`; the
renderer calls `intelligence.generator.extract_visual_fields()` inline on first
render to backfill, so old drafts upgrade silently.

Rendered PNGs land in the Supabase Storage bucket configured by
`SUPABASE_STORAGE_BUCKET` (public bucket; LinkedIn's media-upload API needs a
fetchable URL). `GeneratedAsset.image_path` stores the within-bucket key only;
the public URL is constructed from `settings.SUPABASE_URL + bucket + path` in
the API schema, so swapping storage vendors is a URL-template change, not a
schema migration.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import base64

from app.config import settings
from app.intelligence.generator import (
    AI_IMAGE_BRAND_STYLE_SUFFIX,
    extract_ai_image_prompt,
    extract_visual_fields,
)
from app.models.base import PostCategory, RenderKind
from app.models.generated_asset import GeneratedAsset
from app.models.post import Post
from app.models.template import Template
from app.rendering import playwright_runner, storage
from app.rendering.ai_image import generate_image

log = structlog.get_logger(__name__)

# `backend/app/rendering/templates/`  — Jinja2-templated HTML files
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Square 1:1 — LinkedIn's most reliable feed aspect ratio.
DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 1200

# AI-image frame options → template name. Chosen per render via the request's
# `frame` field; the operator picks how much brand chrome wraps the Flux image:
#   card → full black brand card, image inset 800x800 (seeded 3b27fdcf2346)
#   mark → full-bleed image + small corner brand mark (seeded a3d1e6f92c74)
#   none → full-bleed image, no chrome at all (seeded f2c9a7d41b60)
AI_IMAGE_WRAP_TEMPLATE = "ai_image_wrap"
AI_IMAGE_MARK_TEMPLATE = "ai_image_mark"
AI_IMAGE_BARE_TEMPLATE = "ai_image_bare"

AI_IMAGE_FRAME_TEMPLATES: dict[str, str] = {
    "card": AI_IMAGE_WRAP_TEMPLATE,
    "mark": AI_IMAGE_MARK_TEMPLATE,
    "none": AI_IMAGE_BARE_TEMPLATE,
}
DEFAULT_AI_IMAGE_FRAME = "card"

# AI images render as JPEG (photographic → PNG is too large for the storage
# object cap). q85 is a strong quality/size balance; LinkedIn recompresses
# uploads anyway so higher offers no visible gain.
AI_IMAGE_JPEG_QUALITY = 85


_jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


# Human-readable eyebrow string per post category.
_CATEGORY_LABELS: dict[PostCategory, str] = {
    PostCategory.founder_insight: "Founder insight",
    PostCategory.engineering_lesson: "Engineering lesson",
    PostCategory.ai_automation: "AI · Automation",
    PostCategory.startup_opinion: "Startup opinion",
    PostCategory.technical_humor: "Technical humor",
    PostCategory.carousel: "Carousel",
}

# Default visual template for each post category, by `Template.name`.
# Multiple post categories can share a template (quote/insight overlap is intentional).
_DEFAULT_TEMPLATE_BY_CATEGORY: dict[PostCategory, str] = {
    PostCategory.founder_insight: "insight_card",
    PostCategory.engineering_lesson: "quote_card",
    PostCategory.ai_automation: "metric_card",
    PostCategory.startup_opinion: "quote_card",
    PostCategory.technical_humor: "insight_card",
    PostCategory.carousel: "carousel_slide",
    # Phase 12 Chunk B — new categories. (.get() already falls back to
    # insight_card, but explicit mappings give each a sensible default visual.)
    PostCategory.dev_tooling: "quote_card",  # engineering-leaning, like engineering_lesson
    PostCategory.pricing_business_model: "metric_card",  # numbers-heavy; metric→insight fallback below if no real metric
    PostCategory.product_postmortem: "quote_card",
    PostCategory.design_thinking: "insight_card",
}


def default_template_name_for_post(post: Post) -> str:
    """Pick the default template for a post.

    Smart fallback: if the category maps to `metric_card` but Stage 4 didn't
    find a real numeric metric, use `insight_card` instead — otherwise the
    metric_card fallback renders the whole hook at 112px and long hooks
    overflow the 1200×1200 canvas. The user can still pick `metric_card`
    explicitly; this only affects auto-pick.
    """
    auto = _DEFAULT_TEMPLATE_BY_CATEGORY.get(post.category, "insight_card")
    if auto == "metric_card":
        extracts = post.extracts or {}
        if not extracts.get("metric_value"):
            return "insight_card"
    return auto


def default_context_for_post(
    post: Post, *, slide_index: int = 1
) -> dict[str, Any]:
    """The variables every template can rely on receiving.

    `slide_index` (1-based) only matters for `carousel_slide`; the others ignore
    it. Out-of-range indexes clamp into the slides list — never raises.

    Templates fall back to `hook` whenever an extract field is missing, so this
    function is safe to call on posts where `extracts` is None.
    """
    category = (
        post.category.value if hasattr(post.category, "value") else str(post.category)
    )
    extracts: dict[str, Any] = post.extracts or {}

    pull_quote = extracts.get("pull_quote") or post.hook
    metric_value = extracts.get("metric_value")
    metric_label = extracts.get("metric_label")

    slides = extracts.get("carousel_slides") or []
    if not slides:
        # Single-slide fallback so carousel_slide.html still renders meaningful content.
        slides = [{"text": post.hook}]
    slide_total = len(slides)
    idx = max(1, min(int(slide_index), slide_total))
    slide_text = str(slides[idx - 1].get("text") or post.hook)

    return {
        "hook": post.hook,
        "body": post.body,
        "tags": list(post.tags or []),
        "brand_name": settings.BRAND_NAME,
        "category_label": _CATEGORY_LABELS.get(post.category, category),
        # Stage 4 extracts (with hook fallback for pull_quote, slide_text)
        "pull_quote": pull_quote,
        "metric_value": metric_value,
        "metric_label": metric_label,
        "slide_text": slide_text,
        "slide_number": idx,
        "slide_total": slide_total,
    }


def render_html(template_name: str, context: dict[str, Any]) -> str:
    """Pure Jinja2 render. No browser, no I/O. Useful in tests."""
    template = _jinja_env.get_template(template_name)
    return template.render(**context)


async def render_png(
    template_name: str,
    context: dict[str, Any],
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    image_format: str = "png",
    quality: int | None = None,
) -> bytes:
    """Jinja2 → HTML → image bytes. Requires playwright_runner to be started.

    Defaults to PNG (text/graphic templates). Pass `image_format='jpeg'` +
    `quality` for photographic AI-image renders that would be too large as PNG.
    """
    html = render_html(template_name, context)
    return await playwright_runner.html_to_png(
        html, width=width, height=height, image_format=image_format, quality=quality
    )


async def _pick_template(
    session: AsyncSession, post: Post, template_id: UUID | None
) -> Template:
    """Load Template by explicit id, or pick the default for the post category."""
    if template_id is not None:
        template = await session.get(Template, template_id)
        if template is None:
            raise ValueError(f"template {template_id} not found")
        return template
    name = default_template_name_for_post(post)
    stmt = select(Template).where(Template.name == name)
    template = (await session.execute(stmt)).scalar_one_or_none()
    if template is None:
        raise ValueError(
            f"default template '{name}' not seeded — run alembic upgrade head"
        )
    return template


async def render_post(
    session: AsyncSession,
    *,
    post_id: UUID,
    template_id: UUID | None = None,
    slide_index: int = 1,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    kind: RenderKind = RenderKind.template,
    frame: str = DEFAULT_AI_IMAGE_FRAME,
) -> GeneratedAsset:
    """Render a post → write PNG to disk → persist GeneratedAsset row.

    Each call produces a *new* asset (new UUID, new file). Old assets stay so
    the user can compare prior renders during iteration.

    `kind` selects the renderer backend:
      - `RenderKind.template` (default) — Playwright + Jinja2 HTML template.
      - `RenderKind.ai_image` — AI-generated Flux image. `frame` picks how much
        brand chrome wraps it: 'card' (default) = full brand card, 'mark' =
        full-bleed + small corner brand mark, 'none' = full-bleed no chrome.
        `frame` is ignored for `RenderKind.template`.

    If `post.extracts` is None (older draft predating Stage 4), runs Stage 4
    inline against `post.body` and persists the result. Adds ~1s to the first
    render of an old draft. Subsequent renders skip this.
    """
    post = await session.get(Post, post_id)
    if post is None:
        raise ValueError(f"post {post_id} not found")

    if post.extracts is None:
        log.info(
            "renderer.lazy_extract",
            post_id=str(post.id),
            reason="extracts NULL — backfilling on first render",
        )
        post.extracts = await extract_visual_fields(
            voiced_text=post.body, post_id=post.id
        )
        # Commit alongside the GeneratedAsset write below.

    if kind is RenderKind.ai_image:
        return await _render_ai_image(
            session, post, template_id=template_id, width=width, height=height, frame=frame
        )
    return await _render_template(
        session,
        post,
        template_id=template_id,
        slide_index=slide_index,
        width=width,
        height=height,
    )


async def _render_template(
    session: AsyncSession,
    post: Post,
    *,
    template_id: UUID | None,
    slide_index: int,
    width: int,
    height: int,
) -> GeneratedAsset:
    """Existing path: Jinja2 HTML template → Playwright PNG → asset row."""
    template = await _pick_template(session, post, template_id)
    context = default_context_for_post(post, slide_index=slide_index)
    png_bytes = await render_png(
        template.html_path, context, width=width, height=height
    )

    asset_id = uuid4()
    rel_path = f"{post.id}/{asset_id}.png"
    await storage.upload_image(rel_path, png_bytes)

    asset = GeneratedAsset(
        id=asset_id,
        post_id=post.id,
        template_id=template.id,
        image_path=rel_path,
        width=width,
        height=height,
        render_kind=RenderKind.template,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)

    log.info(
        "renderer.post_rendered",
        post_id=str(post.id),
        kind="template",
        template=template.name,
        slide_index=context["slide_number"],
        slide_total=context["slide_total"],
        asset_id=str(asset.id),
        bytes=len(png_bytes),
    )
    return asset


async def _ensure_ai_image_prompt(session: AsyncSession, post: Post) -> str:
    """Return `post.extracts.ai_image_prompt`, Stage-5-backfilling if absent.

    Older drafts that predate Phase 10 won't have this key. We run Stage 5
    inline against `post.body` and persist the result onto the same JSONB
    field, so subsequent AI-image renders skip the LLM call.
    """
    extracts: dict[str, Any] = post.extracts or {}
    existing = extracts.get("ai_image_prompt")
    if isinstance(existing, str) and existing.strip():
        return existing

    log.info(
        "renderer.lazy_ai_image_prompt",
        post_id=str(post.id),
        reason="ai_image_prompt missing — Stage-5 backfilling",
    )
    prompt_str = await extract_ai_image_prompt(
        voiced_text=post.body, post_id=post.id
    )
    extracts["ai_image_prompt"] = prompt_str
    post.extracts = extracts
    return prompt_str


async def _load_template_by_name(session: AsyncSession, name: str) -> Template:
    stmt = select(Template).where(Template.name == name)
    template = (await session.execute(stmt)).scalar_one_or_none()
    if template is None:
        raise ValueError(
            f"template '{name}' not seeded — run alembic upgrade head"
        )
    return template


async def _render_ai_image(
    session: AsyncSession,
    post: Post,
    *,
    template_id: UUID | None,
    width: int,
    height: int,
    frame: str = DEFAULT_AI_IMAGE_FRAME,
) -> GeneratedAsset:
    """AI-image path: Flux bytes → composite → asset row.

    Steps:
      1. Resolve the Stage-5 visual prompt (Chunk C), lazily backfilling on
         older drafts that predate Phase 10.
      2. Call `generate_image(prompt)` — Cloudflare flux-1-schnell primary,
         Pollinations fallback (composer in app.rendering.ai_image).
      3. Base64-encode the Flux bytes into a data URI and render the AI-image
         template picked by `frame` (see `AI_IMAGE_FRAME_TEMPLATES`): 'card' =
         full brand card (image inset 800x800 + strap), 'mark' = full-bleed +
         small corner brand mark, 'none' = full-bleed no chrome. All 1200x1200.
      4. Playwright → final PNG → Supabase upload → GeneratedAsset row.

    An explicit `template_id` always wins and overrides the `frame` template
    pick — that's the escape hatch for future brand-wrap variants. An unknown
    `frame` falls back to the default ('card').
    """
    prompt_str = await _ensure_ai_image_prompt(session, post)

    # Stage 5 writes a palette-neutral subject. Append the brand style suffix
    # only when the operator opts in — otherwise Flux is free to choose the
    # palette/lighting that best fit the subject (no forced black framing).
    if settings.AI_IMAGE_BRAND_STYLE:
        prompt_str = f"{prompt_str} {AI_IMAGE_BRAND_STYLE_SUFFIX}"

    flux_bytes = await generate_image(prompt_str)
    data_uri = "data:image/png;base64," + base64.b64encode(flux_bytes).decode("ascii")

    if template_id is not None:
        template = await session.get(Template, template_id)
        if template is None:
            raise ValueError(f"template {template_id} not found")
    else:
        name = AI_IMAGE_FRAME_TEMPLATES.get(frame, AI_IMAGE_WRAP_TEMPLATE)
        template = await _load_template_by_name(session, name)

    category_label = _CATEGORY_LABELS.get(post.category, post.category.value)
    context = {
        "hook": post.hook,
        "brand_name": settings.BRAND_NAME,
        "category_label": category_label,
        "image_data_uri": data_uri,
    }
    # JPEG, not PNG: these frames are full-frame photographs. A lossless 2×
    # PNG runs ~4MB and tips past the storage object-size cap on detailed
    # images; JPEG q85 is ~0.5-1MB at the same resolution. Text-card templates
    # stay PNG (see _render_template) where lossless text matters.
    img_bytes = await render_png(
        template.html_path, context, width=width, height=height,
        image_format="jpeg", quality=AI_IMAGE_JPEG_QUALITY,
    )

    asset_id = uuid4()
    rel_path = f"{post.id}/{asset_id}.jpg"
    await storage.upload_image(rel_path, img_bytes, content_type="image/jpeg")

    asset = GeneratedAsset(
        id=asset_id,
        post_id=post.id,
        template_id=template.id,
        image_path=rel_path,
        width=width,
        height=height,
        render_kind=RenderKind.ai_image,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)

    log.info(
        "renderer.post_rendered",
        post_id=str(post.id),
        kind="ai_image",
        template=template.name,
        asset_id=str(asset.id),
        flux_bytes=len(flux_bytes),
        composite_bytes=len(img_bytes),
        prompt_preview=prompt_str[:80],
    )
    return asset


async def render_post_carousel(
    session: AsyncSession,
    *,
    post_id: UUID,
    template_id: UUID | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> list[GeneratedAsset]:
    """Render EVERY slide of a carousel post in order. Returns the asset list.

    Each slide gets its own GeneratedAsset row + PNG upload. The picked template
    must be `carousel_slide` (the only multi-slide template); other templates
    are single-image and should go through `render_post()`.

    Same lazy-Stage-4 backfill semantics as `render_post()` — old drafts get
    extracted on first call.

    Slide count comes from `post.extracts.carousel_slides`. If that's missing
    (Stage 4 returned nothing usable), falls back to a single slide containing
    the hook so the caller never gets an empty list.
    """
    post = await session.get(Post, post_id)
    if post is None:
        raise ValueError(f"post {post_id} not found")

    if post.extracts is None:
        log.info(
            "renderer.lazy_extract",
            post_id=str(post.id),
            reason="extracts NULL — backfilling on first carousel render",
        )
        post.extracts = await extract_visual_fields(
            voiced_text=post.body, post_id=post.id
        )

    template = await _pick_template(session, post, template_id)
    if template.name != "carousel_slide":
        raise ValueError(
            f"render_post_carousel requires the carousel_slide template, "
            f"got '{template.name}'"
        )

    slides = (post.extracts or {}).get("carousel_slides") or [{"text": post.hook}]
    n = len(slides)

    assets: list[GeneratedAsset] = []
    for i in range(1, n + 1):
        context = default_context_for_post(post, slide_index=i)
        png_bytes = await render_png(
            template.html_path, context, width=width, height=height
        )
        asset_id = uuid4()
        rel_path = f"{post.id}/{asset_id}.png"
        await storage.upload_image(rel_path, png_bytes)

        asset = GeneratedAsset(
            id=asset_id,
            post_id=post.id,
            template_id=template.id,
            image_path=rel_path,
            width=width,
            height=height,
            slide_index=i,
            render_kind=RenderKind.template,
        )
        session.add(asset)
        assets.append(asset)

    # One commit at the end so a mid-loop failure leaves no partial state.
    # If render_png or upload_image raises mid-loop, no rows persist.
    await session.commit()
    for a in assets:
        await session.refresh(a)

    log.info(
        "renderer.carousel_rendered",
        post_id=str(post.id),
        template=template.name,
        slide_count=n,
        asset_ids=[str(a.id) for a in assets],
    )
    return assets
