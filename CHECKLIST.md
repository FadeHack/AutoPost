# CHECKLIST.md — Implementation Status

Markdown-checkbox tracker. Updated after every implementation step. `[x]` = done, `[ ]` = pending. Blockers and tech debt at the bottom.

---

## Phase 0 — Scaffolding ✅ (complete)

- [x] Create monorepo directory tree (`backend/`, `frontend/`, subsystem folders, tests)
- [x] Seed `CLAUDE.md` (rules + guardrails)
- [x] Seed `CONTEXT.md` (architecture memory)
- [x] Seed `CHECKLIST.md` (this file)
- [x] Seed `INSTRUCTIONS.md` (operational runbook)
- [x] Create root `.gitignore`
- [x] Create root `.env.example`
- [x] Create root `README.md`
- [x] Backend: create `venv` (Python 3.12), `requirements.txt`
- [x] Backend: FastAPI hello-world (`app/main.py` with `/health` + `/`)
- [x] Backend: `app/config.py` (pydantic-settings)
- [x] Backend: `app/core/logging.py` (structlog)
- [x] Backend: `app/db.py` (SQLAlchemy async engine + session + `Base`)
- [x] Backend: Alembic init + `alembic.ini` + async `env.py`
- [x] Frontend: Next.js 16 + React 19 + Tailwind 4 + TypeScript + App Router (scaffolded into `frontend/`)
- [x] Frontend: `.env.local.example`
- [x] Verify backend boots via `uvicorn app.main:app` (200 on `/health`)
- [x] Verify frontend boots via `npm run dev` (200 on `/`)
- [ ] `git init` and initial commit (when user requests)

---

## Phase 1 — Schema + Auth ✅ (complete)

### Prerequisites (user gathers credentials)
- [ ] Generate `APP_SECRET_KEY` via `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- [ ] Provision Supabase project → copy **Session Pooler** URL (port 5432) + anon/service-role keys
- [ ] Get Groq API key from console.groq.com (no card)
- [ ] Get LinkedIn App #1 credentials (CLIENT_ID + CLIENT_SECRET) — already set up
- [ ] Create Reddit script-type app → get CLIENT_ID + CLIENT_SECRET
- [ ] Fill `backend/.env` with all of the above; fill `frontend/.env.local` with the `NEXT_PUBLIC_*` values

### Schema ✅
- [x] Alembic migration 0001: all 10 tables (users, linkedin_accounts, trends, prompts, templates, posts, generated_assets, ai_generations, publishing_logs, analytics)
- [x] `linkedin_accounts` schema includes `account_kind` enum (`'personal'`,`'organization'`), `member_sub`, nullable `org_urn`, `scopes` text[]
- [x] SQLAlchemy ORM models (one file per table under `backend/app/models/`)
- [x] `alembic upgrade head` runs cleanly against Supabase Session Pooler URL
- [x] Verified: 11 tables + alembic_version + 7 enum types live in Supabase `public` schema

### Auth (dashboard) ✅
- [x] Frontend: Supabase Auth client (`lib/supabase.ts`) + `AuthProvider` context + magic-link login page (`/login`)
- [x] Backend: Supabase JWT verification via JWKS (ES256/RS256/EdDSA) — `app/core/auth.py::get_current_user`. Optional HS256 fallback via `SUPABASE_JWT_SECRET` for legacy projects.
- [x] JIT user provisioning (first JWT verification creates the `users` row)

### Auth (LinkedIn — single app, personal posting) ✅
- [x] Backend: `app/core/security.py` — Fernet `encrypt`/`decrypt` + TTL-aware variant for OAuth state
- [x] Backend: `app/publishing/oauth.py` — encode/decode state (Fernet + 10-min TTL), build authorize URL, code exchange, refresh, OIDC userinfo
- [x] Backend: `app/api/auth_linkedin.py` with `/auth/linkedin/start`, `/auth/linkedin/callback`, `/auth/linkedin/status`
- [x] On callback: fetch OIDC `userinfo`, store `sub` as `linkedin_accounts.member_sub`, `account_kind='personal'`, encrypted access/refresh tokens, scopes array
- [x] API router mounted at `/api/v1` — OpenAPI shows `/start`, `/callback`, `/status`
- [x] Frontend: "Connect LinkedIn" button on dashboard with status display + reconnect

### Verify ✅
- [x] Signed in via Supabase magic link → landed on dashboard
- [x] Clicked "Connect LinkedIn" → completed OAuth → callback succeeded → `linkedin_accounts` row created with `account_kind='personal'` and `expires_at` set (verified end-to-end by user)

---

## Phase 2 — Retrieval Layer ✅ (complete)

### Chunk A — Fetchers + dedupe ✅
- [x] `app/retrieval/base.py` — `Fetcher` ABC + `TrendItem` dataclass
- [x] `app/retrieval/rss.py` — 6 locked feeds (Stratechery, First Round, Stripe, Pragmatic Engineer, OpenAI, Hugging Face), `httpx` + `feedparser`, polite UA, in-memory ETag / Last-Modified cache, parallel via `asyncio.gather`
- [x] `app/retrieval/hackernews.py` — top 30 + best 20 via `hacker-news.firebaseio.com/v0`, skips dead/deleted/non-story items, falls back to HN item URL when external `url` missing
- [x] `app/retrieval/reddit.py` — written but **disabled in orchestrator until Reddit Data API approval** (PRAW in `asyncio.to_thread`, 8 starter subreddits)
- [x] `app/retrieval/dedupe.py` — URL normalization (strips utm_*, fbclid, gclid, ref, trailing slash, lowercases host) + trigram-Jaccard title similarity at threshold 0.85
- [x] Smoke-verified: all 5 modules import cleanly, dedupe collapses URL+title duplicates correctly

### Chunk B — Orchestrator + scheduler + endpoints ✅
- [x] `app/retrieval/orchestrator.py` — calls enabled fetchers in priority order (RSS → HN), dedupes, bulk-inserts via `INSERT ... ON CONFLICT DO NOTHING ... RETURNING id`
- [x] `app/scheduler/scheduler.py` + `app/scheduler/jobs.py` — APScheduler AsyncIOScheduler with `SQLAlchemyJobStore` (sync URL coerced), `retrieval_job()` registered on cron `RETRIEVAL_CRON`
- [x] Scheduler started in FastAPI `lifespan` hook in `app/main.py` (startup log lists registered job IDs)
- [x] `POST /api/v1/trends/refresh` endpoint (manual trigger, auth required)
- [x] `GET /api/v1/trends?status={unconsumed|consumed|all}&source=...&limit=N` endpoint
- [x] RSS: First Round Review dropped (RSS discontinued, both URLs 404); per-feed cap of 25 + 90-day age cutoff added to keep unconsumed pool fresh
- [x] End-to-end verified: orchestrator pulls 180 items / run from real feeds (7 RSS + HN) into Supabase; backend boots with scheduler started; both endpoints return 403 unauthenticated
- [x] **RSS feeds expanded to 7**: added Simon Willison (independent AI commentary, multi/day) + Latent Space (AI engineering, 2-3×/week)
- [x] Cleared 1,837-row pre-cap flood via `TRUNCATE TABLE trends` — fresh pool for Phase 3

### Chunk C — Frontend + e2e verify ✅
- [x] Backend: `PATCH /api/v1/trends/{id}` (consume toggle, body `{consumed: bool}`)
- [x] Frontend: `apiPatch` helper in `lib/api.ts`
- [x] Frontend: `/trends` page — status + source filters, refresh button with summary banner, per-row consume toggle with optimistic UI, source-coded badges
- [x] Frontend: dashboard "Trends" card linking to `/trends`
- [x] End-to-end verified by user in browser: refresh → trends populate → filter / consume / mark-unread all work
- [x] Tests: 27 passing in <0.4s — `test_dedupe.py` (URL normalization, title similarity, dedupe), `test_rss.py` (happy-path, age cutoff, per-feed cap, 304, isolated failures), `test_hackernews.py` (top+best dedup, skip dead/deleted/non-story, fallback URL, score capture)
- [x] `backend/pyproject.toml` added for pytest config (asyncio auto-mode)

---

## Phase 3 — Intelligence Layer

**Locked design decisions** (carry over post-compact):
- **Article body fetched on-demand at generation time**, not pre-fetched at retrieval. `trafilatura` extracts clean text from each picked URL; LLM gets `title + summary + clean article body` per trend. Graceful fallback to title+summary if fetch fails (paywall, 404).
- **Voice direction: contrarian + builder-grounded.** Anchored via 2-3 example posts inside each prompt template (LLM follows examples > rules). Signature pattern per post: contrarian/confessional hook → one specific concrete detail → punchy takeaway. No survey-of-perspectives, no closing summary. Prompts live in the `prompts` table so voice tuning needs no code deploys.
- **Prerequisites confirmed:** `GROQ_API_KEY` present in `backend/.env`.

### Chunk A — Infrastructure ✅
- [x] `trafilatura==2.0.0` + `groq==1.4.0` (bumped from 0.15.0) pinned in `requirements.txt` (web-verified per CLAUDE.md rule)
- [x] `app/intelligence/groq_client.py` — `chat(stage, messages, ...)` entry point; `AsyncGroq` + `tenacity` `AsyncRetrying` (4 attempts, exp backoff 1–10s) retrying only `APIConnectionError` / `RateLimitError`; every call writes an `ai_generations` audit row (input, output, tokens, latency, stage) via `_log_generation` whose own failures are logged not raised
- [x] `app/intelligence/article.py` — `fetch_article(url)` via httpx (10s timeout, polite UA, follow redirects) + `trafilatura.extract` in `asyncio.to_thread` (favor_precision, no comments/tables); 8K char cap; any failure (network / non-200 / empty extraction) returns `None`
- [x] Tests: 12 passing in <2s — `test_groq_client.py` (happy path, default model, response_format pass-through + omission, non-retryable propagates + still audits, retryable then success counts attempts + one audit row, missing API key raises); `test_article.py` (extracts + strips boilerplate, non-200 → None, network error → None, unextractable HTML → None, truncation to MAX_CHARS)

### Chunk B — Voice + prompts + generator ✅
- [x] `app/intelligence/voice.py` — `strip_ai_tells(text) → (cleaned, violations)` (em-dash separator → period, closing-summary paragraph drop, 10 banned phrases stripped case-insensitively, whitespace tidying — idempotent). `polish_voice(text)` optional second LLM pass on `GROQ_MODEL_FAST` (constrained rewrite) — called explicitly, never auto-triggered.
- [x] Alembic migration `c7a4f1e8b2d3_seed_prompts.py` — 4 prompts seeded into `prompts` table, all v1 + `is_active=true`. Each ~2K-char body: voice rules, 3 anchor example posts (contrarian/confessional hook → concrete specific → punchy takeaway), and category-specific framing. Applied to Supabase; all 4 visible.
  - `founder_insight`, `engineering_lesson`, `ai_automation`, `startup_opinion`
- [x] `app/intelligence/generator.py` — 3-stage pipeline split into `run_pipeline()` (pure LLM, testable in isolation) + `generate_draft()` (DB orchestration). Stage 1 angle (primary, T=0.85) → Stage 2 voice rewrite (primary, T=0.7) → `strip_ai_tells` → Stage 3 extract (FAST, T=0, `response_format=json_object`) → `_parse_extract` with graceful fallback on bad JSON. `generate_draft` loads active prompt, picks ≤3 trends (caller-supplied IDs or unconsumed by score+freshness), fetches article bodies in parallel, persists `Post(status=draft)`, marks source trends `consumed_at`.
- [x] `POST /api/v1/posts/generate` (body: `{category, trend_ids?}`) → returns draft; `GET /api/v1/posts?status=&limit=` (newest-first); `GET /api/v1/posts/{post_id}`. Router mounted at `/api/v1/posts` in `app/api/__init__.py`. All auth-gated (verified 403 unauthenticated).
- [x] Tests: 27 new tests in `tests/intelligence/` covering voice (14: em-dash separator, closing summary, 10 banned phrases case-insensitively, whitespace tidying, idempotence) + generator (13: `_parse_extract` happy/bad-JSON/hash-strip/cap-3/dedupe/non-list/missing-hook, `_format_trend` includes/omits/truncates, full 3-stage flow asserts stage order + models + prompt_id propagation + JSON format, voice strip runs between stages 2 and 3, bad JSON in stage 3 falls back). 66 total passing in <2s.

### Chunk C — Drafts queue UI ✅
- [x] `frontend/app/drafts/page.tsx` — list view: status filter dropdown (draft / approved / scheduled / published / failed / all), inline "Generate a draft" card with category dropdown, category + status colored badges per row, hook preview, hashtag row, click-through to detail. Hot-fetches after a generation completes.
- [x] `frontend/app/drafts/[id]/page.tsx` — read-only detail view (category + status badges, hook section, full body in pre-wrap, tags row, source-trend-count + post ID metadata, "Generate another" CTA that routes to the new draft). Uses Next.js 16 `params: Promise<{id}>` + `React.use()` per the in-repo Next.js docs (the AGENTS.md flag was real — `params` is no longer sync).
- [x] Dashboard nav: replaced "Coming soon" placeholder with a Drafts card linking to `/drafts`.
- [x] Browser e2e verified by user: generate (each of the 4 active categories) → draft appears → click → detail view → "Generate another" routes correctly.

### Phase 3 voice-iteration history
The first-pass v1 prompts produced posts that read as obvious AI output. Three migration rounds tuned the voice without code changes (the [versioned `prompts` table](backend/app/models/prompt.py) is doing its job — voice tuning is a DB write, not a deploy):
- **v1 → v2** (`f3b8a72c9d41_prompts_v2_reaction_style.py`): v1's anchor examples were first-person achievement stories ("I shipped a 'better' onboarding for six weeks") which the model interpreted as license to fabricate autobiography from whatever the trend said (`"I made a million dollar product from my dorm room"` lifted verbatim from a HN post about nice!nanos keyboards). v2 replaces anchors with reaction-style examples ("Saw a thread claiming X. Disagree because…") and adds a CRITICAL CONTEXT block: "the trends are things you READ today, you did NOT do them."
- **v2 → v3** (`a5d2b9e4f637_prompts_v3_length_sharpness.py`): v2 outputs collapsed to ~40-55 word tweet-fragments ("Simple is better." / "Cheaper and more reliable.") because the voice rewrite system prompt said "max 12 words per line" and the model interpreted that as max 12 words per sentence. v3 expands the line-length rule to "140-220 words, 4-7 paragraphs, full sentences," and adds a sharp-takeaway rule that explicitly rejects generic affirmations ("AI is real", "simple is better", "humans matter").
- **v3 → v4** (`b4e7c1f293a8_prompts_v4_real_anchors.py`): v3 fixed length but drifted into tech-blog explainer mode. v4 replaces fabricated anchors with examples built around REAL positions held by working founders — Jason Fried on hiring-by-evidence-not-tenure, DHH on small-team microservices as org-theatre, Sahil Lavingia on VC-only-when-VC-is-the-only-fit, Simon Willison on coding-agents-PMF (with his real $2,180/mo + Uber's 25% via Claude Code numbers). Also adds 12 more banned phrases to `voice.py` catching what slipped past v3 ("is also worth noting", "sparked my interest", "I've seen many teams", "one notable aspect", etc.) and a "REACT, DON'T EXPLAIN" rule with an explicit "<25% describes the trend, >75% is YOUR opinion" budget.

### Phase 3 infrastructure tunes (post-v4)
After v4, outputs swung the other way — 280-430 words of explainer text. Two infra-level (not prompt-level) caps fix this without another prompt iteration:
- `generator.py`: `VOICE_MAX_TOKENS` 800 → 350 (hard ceiling on body), `ANGLE_MAX_TOKENS` 800 → 500.
- `article.py`: `MAX_CHARS` 8000 → 2500. Less raw article material for the model to recapitulate.

### Phase 3 status: shipping at ~65-70% voice quality
Voice tuning has hit diminishing returns on prompt iteration without real positive/negative training samples. Deferring further voice work to Phase 8 (Hardening), where we'll have actual generation history to mine for "this was good" / "this was bad" anchors and bump to v5 with sample-driven anchors. Categories, schema, generator pipeline, audit log, and UI are all production-shaped.

---

## Phase 4 — Rendering Layer

### Chunk A — Playwright infra ✅
- [x] `app/rendering/playwright_runner.py` — singleton headless Chromium booted in FastAPI `lifespan` hook. One process-wide browser; throwaway context per render for total isolation. `html_to_png(html, width, height, device_scale_factor=2)` is the only public render primitive.
- [x] FastAPI lifespan now boots/shuts the runner after the scheduler (`app/main.py::lifespan`).
- [x] `BRAND_NAME=Nestwhirr` added to `app/config.py` + `backend/.env.example` (used as the footer-strap brand on every template).
- [x] `playwright install chromium` run locally (Phase 0 only pinned the package; the binary was missing). Confirmed `~/Library/Caches/ms-playwright/chromium_headless_shell-1148`.
- [x] Smoke-verified: minimal `insight_card.html` rendered to a 2400×2400 PNG via the full lifespan loop.

### Chunk B — Templates, renderer, endpoints, tests ✅
- [x] Four HTML/Tailwind templates committed at `app/rendering/templates/`:
  - `insight_card.html` — eyebrow + centered serif headline + accent line + brand strap
  - `quote_card.html` — italic serif + oversized quotation mark anchor (dramatic)
  - `metric_card.html` — top-aligned uppercase bold sans display type (data-card feel)
  - `carousel_slide.html` — slide-indicator + serif headline + swipe-affordance when not last slide
- [x] All four share one minimal-dark identity (black bg, serif headline, sans body, accent line above brand strap). Tailwind via CDN inside each HTML — no build step.
- [x] `app/rendering/renderer.py` two-layer split:
  - Pure: `render_html()` + `render_png()` + `default_template_name_for_post()` + `default_context_for_post()`. Testable in isolation.
  - DB orchestration: `render_post(session, post_id, template_id?)` — loads Post, picks Template (explicit id or category default), renders bytes, writes file at `backend/storage/assets/{post_id}/{asset_id}.png`, persists `GeneratedAsset` row.
- [x] Category → default template mapping in renderer: founder_insight → insight_card, engineering_lesson → quote_card, ai_automation → metric_card, startup_opinion → quote_card, technical_humor → insight_card, carousel → carousel_slide.
- [x] Alembic data migration `d8e2f4a91c56_seed_templates.py` — 4 templates seeded into `templates` table via `op.bulk_insert`. Applied to Supabase; all 4 rows visible.
- [x] Endpoints added to `app/api/posts.py`:
  - `POST /api/v1/posts/{post_id}/render` (body `{template_id?}`) → returns `GeneratedAssetRead` (id, post_id, template_id, image_path, width, height, linkedin_asset_urn, created_at, image_url).
  - `GET /api/v1/posts/{post_id}/assets` → newest-first list.
- [x] `app/api/templates.py` — `GET /api/v1/templates` for the future template-picker UI.
- [x] FastAPI `StaticFiles` mount at `/static/assets` → `backend/storage/assets/`. Dev-only (backend binds to 127.0.0.1 per CLAUDE.md). `GeneratedAssetRead.image_url` is computed as `f"{APP_BASE_URL}/static/assets/{image_path}"` so the frontend can fetch directly.
- [x] Tests: 17 new in `tests/rendering/test_renderer.py` (default-template mapping, default context, Jinja2 escaping, parametrized render-each-template, `render_png` calls playwright with right HTML + dims, `_pick_template` happy/explicit/missing-id/missing-default). **Full suite 87 passing in 1.78s**. No real Chromium, no real DB — `playwright_runner.html_to_png` monkeypatched, `_pick_template` exercised against `unittest.mock.AsyncMock`.
- [x] End-to-end DB-side smoke verified: latest draft → `render_post()` → 153KB PNG written to `backend/storage/assets/{post_id}/{asset_id}.png` + GeneratedAsset row inserted + `template=insight_card` auto-picked from `category=founder_insight`.

### Chunk G — Dedicated "Carousel slides" strip on draft detail ✅
- [x] Slides 2..N were being buried inside the collapsed `"earlier renders"` `<details>` after a carousel render — bad UX for the actual content the user just generated. Split the two concepts:
  - **Carousel slides** (new, always visible) — shows every slide of the most recent carousel batch as thumbnails with `1/N`, `2/N`, ... labels. Click any → full size in a new tab.
  - **Earlier renders** (existing, collapsed) — keeps only what it was meant for: prior render attempts before the current carousel.
- [x] Frontend detects the "current carousel batch" via `useMemo` over `assets`: takes the front-of-list cluster of `carousel_slide` assets whose `created_at` timestamps are within 60s of each other. A 60s window is generous (real carousel batches take ~1-2s per slide); user re-rendering 60s+ later starts a new batch and the previous one rolls into "earlier renders". A single carousel slide (length === 1) doesn't show the strip — same shape as a single-image render.
- [x] `older` slice now starts at `currentCarousel.length || 1` so slides 2..N never appear in both sections.
- [x] TypeScript clean. Page compiles + returns 200.

### Chunk F — One-click carousel rendering (closes the Chunk D UX gap) ✅
- [x] `app/rendering/renderer.py::render_post_carousel(session, *, post_id, template_id?, ...)` — loops through every slide in `post.extracts.carousel_slides`, renders + uploads each, persists N `GeneratedAsset` rows in a single commit. Same lazy-Stage-4 backfill semantics as `render_post()`. Validates the picked template is actually `carousel_slide` (errors otherwise).
- [x] `POST /api/v1/posts/{id}/render-carousel` → returns `list[GeneratedAssetRead]` (one entry per slide, slide-1-first order). Auth-gated like every other route. Errors translate `ValueError` → 400.
- [x] Frontend `/drafts/[id]/page.tsx` dispatches to the right endpoint based on the selected template:
  - Explicit `carousel_slide` pick OR Auto-pick on a `carousel`-category post → `/render-carousel` (N assets in one click)
  - Anything else → `/render` (one asset)
  - Button label adapts: `"Render carousel (5 slides)"` / `"Rendering 5 slides…"` for the carousel path, plain `"Render"` / `"Rendering…"` for single-image.
- [x] `Post` type in the frontend gains `extracts: PostExtracts | null` so the button can show the live slide count from `post.extracts?.carousel_slides?.length`.
- [x] TypeScript clean (`npx tsc --noEmit`).
- [x] Full test suite still 110 passing in 1.78s (no test changes needed — pure-Jinja2 + context tests already cover the surface).
- [x] **End-to-end smoke verified**: rendered the 5-slide `ai_automation` post via `render_post_carousel` directly. 5 separate Supabase Storage POSTs all returned 200; row count delta = 5; one single DB commit at the end (no partial state on a mid-loop failure). Total wall-clock ≈ 6 s for 5 slides.
- [ ] **Browser e2e** — user-driven check: open a carousel post → pick `carousel_slide` from the dropdown (or use Auto on a `carousel`-category post) → click **Render carousel (N slides)** → wait ~6 s → N images persist; latest preview shows slide 1, others tuck into the "earlier renders" thumbnail strip.

### Chunk E — Supabase Storage migration (S3-shaped object storage) ✅
- [x] `supabase==2.13.0` added to `requirements.txt` and installed; deps include `storage3==0.11.3` (the underlying storage client).
- [x] `SUPABASE_STORAGE_BUCKET=autopost-assets` added to `app/config.py` + `backend/.env.example`. User created the `autopost-assets` **public bucket** in the Supabase dashboard. Public so LinkedIn's media-upload API can fetch the URL at publish time without signed-URL gymnastics.
- [x] `app/rendering/storage.py` — Supabase Storage wrapper: lazy module-level `Client` (created from `SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY`), `upload_png(path, png_bytes) -> str` (PNG upload, wraps sync supabase-py in `asyncio.to_thread`), `public_url(path) -> str` (constructs the CDN URL without a network call).
- [x] `app/rendering/renderer.py` updated: removed `ASSETS_DIR` constant and the `abs_path.write_bytes(...)` block; `render_post()` now calls `await storage.upload_png(rel_path, png_bytes)` after rendering. `image_path` shape unchanged (`{post_id}/{asset_id}.png`) — bucket prefix lives in the URL, not the column.
- [x] `app/api/posts.py::GeneratedAssetRead.image_url` switched to `storage.public_url(self.image_path)` — pattern is `{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}`. Frontend `<img>` tag picks it up unchanged.
- [x] `app/main.py` — dropped the `from fastapi.staticfiles import StaticFiles` import, the `from app.rendering.renderer import ASSETS_DIR` import, the `ASSETS_DIR.mkdir(...)` call, and the `app.mount("/static/assets", ...)` block. Backend no longer serves images.
- [x] **End-to-end verified live:** rendered the latest post via the new pipeline; Supabase Storage `POST /storage/v1/object/autopost-assets/...` returned 200; public URL `HEAD` returned 200 with matching `Content-Length: 145777` and `Content-Type: image/png`. CDN is serving.
- [x] **Cleanup:** deleted 17 stale `GeneratedAsset` rows pointing at the old local paths; removed the 2.2 MB `backend/storage/assets/` directory. Posts themselves untouched — `Post` table is the same; the rendering-history scratch was the only collateral.
- [x] Full test suite passes: **110 passing in 1.80s**. Existing renderer tests didn't need changes because `playwright_runner.html_to_png` was already monkeypatched and `render_post()` was already not unit-tested (its DB orchestration is covered by manual end-to-end smoke). The pure-Jinja2 + context-shape tests cover the unchanged surface.

### Chunk D — Stage 4 visual extraction (LLM-driven per-template content) ✅
- [x] Alembic migration `e9f3c5b81d72_add_extracts_to_posts.py` — adds nullable `posts.extracts` JSONB column; existing rows stay NULL (lazy-fill on first re-render).
- [x] `Post.extracts: Mapped[dict|None]` added to ORM model; `PostRead` schema exposes it through the API.
- [x] Stage 4 added to generator (`extract_visual_fields()` is the public surface; `_VISUAL_EXTRACT_SYSTEM` is the FAST-model prompt; `_parse_visual_extract()` tolerantly parses bad JSON / non-dict / missing fields / bare-string slides / orphaned metric_value-without-label).
- [x] Stage 4 wired into `run_pipeline()` → returns 5-tuple `(hook, body, tags, extracts, violations)`. `generate_draft()` persists `extracts` on the new Post. Verified live: ~700ms / ~130 tokens per Stage 4 call, ~$0.0001 per draft on the FAST model.
- [x] Renderer reads from `post.extracts` with hook fallback:
  - `default_context_for_post(post, slide_index=1)` now exposes `pull_quote / metric_value / metric_label / slide_text / slide_number / slide_total`. Missing extract fields fall back to `hook`.
  - `render_post()` accepts `slide_index`; clamps out-of-range values; lazy-extracts (calls Stage 4 inline + persists) on the first render of any pre-Chunk-D draft.
  - `default_template_name_for_post()` got a smart fallback: ai_automation posts without a real metric auto-pick `insight_card` instead of `metric_card` so long hooks don't overflow the canvas.
- [x] Three templates updated to consume extracts:
  - `quote_card.html` — `{{ pull_quote|default(hook) }}`
  - `metric_card.html` — `{% if metric_value %}` shows value at 160px + label, else fallback uses 64px sans bold with `|truncate(140)` for safety
  - `carousel_slide.html` — `{{ slide_text|default(hook) }}` + slide indicator + conditional "swipe →" affordance
- [x] `POST /api/v1/posts/{id}/render` body gains `slide_index: int = 1` (Pydantic validates `ge=1, le=20`).
- [x] Tests: 23 new — 13 in `test_generator.py` (4-stage pipeline assertions, `_parse_visual_extract` tolerance suite, `extract_visual_fields` call shape) + 10 in `test_renderer.py` (extracts in context, slide_index clamping/picking, template branch selection, metric fallback typography signature). **Full suite 110 passing in 1.71s**.
- [x] End-to-end smoke against a fresh `ai_automation` draft: Stage 4 returned 5 carousel slides + a non-hook pull_quote + correct null on metric_value (no real number to invent). Rendered all 4 templates + 5 carousel slides via real Playwright + real Supabase. Spotted + fixed the metric_card overflow bug mid-smoke (added smart auto-pick fallback + tightened fallback typography). Re-rendered → fits cleanly.
- [x] Backwards compat verified: posts predating this Chunk have `extracts=NULL`; renderer falls back to hook everywhere and lazy-fills via Stage 4 on first re-render (visible in the `renderer.lazy_extract` log line).

### Chunk C — Frontend image preview ✅
- [x] `frontend/app/drafts/[id]/page.tsx` now fetches `/posts/{id}`, `/posts/{id}/assets`, and `/templates` in parallel (`Promise.all`) on mount. New types: `Template`, `GeneratedAsset`, `TemplateCategory`.
- [x] New "Visual" section sits above the Hook section. Layout: square preview (left) + template picker dropdown + Render button (right). Picker default is "Auto for category" → backend picks via `_DEFAULT_TEMPLATE_BY_CATEGORY`. Picking an explicit option posts `{template_id}` to `/render`.
- [x] Latest asset rendered via plain `<img>` (cross-origin from backend's `/static/assets`; no Next.js Image config needed). "Open full size →" link to the underlying URL.
- [x] Older renders collapse into a `<details>` thumbnail grid (3-5 cols responsive) — each render produces a new `GeneratedAsset` so the user can scrub history.
- [x] Render button state: idle / "Rendering…" / disabled-while-in-flight. Errors surface inline below the button as monospace text.
- [x] Type-check clean (`npx tsc --noEmit` returns 0).
- [x] Reachability verified: backend `GET /api/v1/templates`, `GET /posts/{id}/assets`, `POST /posts/{id}/render` all return 403 unauthenticated (auth gating). Frontend `/drafts/{id}` returns 200 (page compiles + renders). Static asset URL serves 200.
- [ ] **Browser e2e** — user-driven check. Open a draft → click Render → wait ~3-5s → image appears in the preview slot. Pick a different template, click Re-render, verify a new image replaces it and the previous one moves into the "earlier renders" details strip.

---

## Phase 5 — Dashboard Core

Chunked: A (editing) → B (approve + LinkedIn preview) → C (schedule + queue pages).

### Chunk A — Editing path ✅
- [x] Backend: `PATCH /posts/{id}` with `{hook?, body?, tags?}` body — gated on `status='draft'` (returns 409 otherwise per the no-skip lifecycle). Tag normalization helper (lowercase, strip leading `#`, trim, dedupe, cap at 6, max-length 40) applied server-side so manual edits stay within the voice guideline.
- [x] Backend: 8 new unit tests for `normalize_tags` (lowercase + hash strip, empty/whitespace drop, order-preserving dedupe, hash-strip-then-dedupe, MAX_TAGS cap, MAX_TAG_LENGTH truncation, non-string skip, empty input). **Full suite 118 passing in 1.91s.**
- [x] Frontend: `components/DraftEditor.tsx` — extracted client component. Auto-resizing textareas for hook + body (ref + scrollHeight effect), tag chip input (Enter or comma to add, Backspace on empty input pops last chip, × to remove), dirty tracking via memo (compares hook/body/tags vs initial), Save disabled until dirty + non-empty + not saving.
- [x] Frontend: `/drafts/[id]/page.tsx` wires the editor — new `editing` / `saving` / `editError` state, `apiPatch<Post>` call on save (updates page state from response + exits edit mode), Cancel discards. Edit button on the action bar is disabled with a tooltip when `post.status !== 'draft'`. Visual + metadata sections stay visible during edit; only the read-only Hook + Body sections are swapped out.
- [x] TypeScript clean (`npx tsc --noEmit`). New PATCH route registered (verified via router enumeration).
- [ ] **Browser e2e** — user-driven check. Open a draft → click Edit → tweak hook + body + tags → Save → page re-renders with updated values + exits edit mode. Try a non-draft post: Edit button shows disabled with the lock tooltip.

### Chunk B — Approve flow + LinkedIn preview + status-aware CTAs ✅
- [x] Backend: `POST /posts/{id}/approve` — `draft → approved` per the no-skip lifecycle; returns 404 if missing, 409 with `"cannot approve post in status 'X'"` if not draft. Returns refreshed `PostRead`. Verified registered alongside the other `/posts` routes via router enumeration.
- [x] Frontend: `components/LinkedInPreview.tsx` — feed-card chrome with avatar (initials gradient), name + "· 1st", title line ("Founder · Nestwhirr" by default), "now · 🌐", body with `whitespace-pre-wrap` so generator line breaks survive, hashtags rendered in LinkedIn blue (`#0a66c2`), single-image OR carousel slot (carousel shows slide 1 + "1 / N" badge + "swipe →" affordance), stub reactions row + Like/Comment/Repost/Send action bar. Not pixel-perfect — signal is "line breaks, hashtags, image-hang", not chrome accuracy.
- [x] Frontend: `/drafts/[id]/page.tsx` wires both:
  - **LinkedIn preview** section between Visual and Hook. Uses `latest?.image_url` for single-image posts, falls back to `currentCarousel` (the Chunk G memo from Phase 4) when N>1 carousel slides exist. Author name pulled from Supabase session email's local part.
  - **Approve button** on the action bar — blue CTA. Disabled with status-aware tooltip when `post.status !== 'draft'` (shows "Already approved" / "Cannot approve a post in status 'X'"). Label transitions to "Approved ✓" once flipped. After approve, `setPost(updated)` swaps the status badge AND auto-disables the Edit button (Chunk A lifecycle rule still holds).
- [x] TypeScript clean (`npx tsc --noEmit`). Full backend suite **118 passing in 1.92s** (no new tests — approve endpoint has no pure logic worth unit-testing beyond the status gate, which is one branch).
- [ ] **Browser e2e** — user-driven check. Open a draft → see the LinkedIn preview render with the latest image and full body → click Approve → button flips to "Approved ✓", status badge turns blue, Edit greys out, action bar unchanged otherwise.

### Chunk C — Schedule + queue pages ✅
- [x] Backend: `POST /posts/{id}/schedule` body `{scheduled_at: datetime}` — accepts `status` in `{approved, scheduled}` so the same endpoint handles initial schedule AND reschedule (idempotent). Naive datetimes are tagged UTC at the boundary. Rejects times within `MIN_SCHEDULE_LEAD_SECONDS=60s` of now (400). Sets `post.scheduled_at` + flips status to `scheduled` + commits. APScheduler job registration is intentionally deferred to Phase 6 — this endpoint just persists the intent.
- [x] Frontend: `components/SchedulePicker.tsx` — `<input type="datetime-local">` in the user's local TZ (label shown), default value is `now + 15 min` rounded to the next 5-min mark, client-side validation mirrors the 60s server gate with a small skew buffer (70s), live relative-time hint ("in 2 hr"), submits as an explicit UTC ISO string via `toISOString()`. Re-uses initial value when rescheduling.
- [x] Frontend: `/drafts/[id]/page.tsx` wires the picker — new `scheduling` / `schedulePickerOpen` / `scheduleError` state, blue **Schedule / Reschedule** button on the action bar (enabled only when status in `{approved, scheduled}`), inline picker panel above the action row, scheduled-time banner stays visible once set. After a successful schedule, the page state flips status to `scheduled` and the badge + action bar update.
- [x] Frontend: `/scheduled` page — list view, fetches `GET /posts?status=scheduled&limit=100`, sorts client-side by `scheduled_at` ASC (next-up first), shows category badge + status badge + scheduled date + relative time, click-through to detail.
- [x] Frontend: `/published` page — list view, fetches `GET /posts?status=published&limit=100`, sorts by `published_at` DESC. Each row links to the LinkedIn post via a small `linkedinUrlFromUrn()` helper that converts `urn:li:share:NNN` / `urn:li:ugcPost:NNN` to the public `https://www.linkedin.com/feed/update/urn:li:activity:NNN/` URL (LinkedIn redirects the activity-id form regardless of source URN). Empty state points back to `/scheduled` since nothing publishes until Phase 6.
- [x] Frontend: Dashboard cards — replaced the "Coming soon" placeholder with separate **Scheduled** and **Published** cards, kept a thinner "Coming soon" stub pointing at Phases 6 + 7.
- [x] **Test suite still 118 passing in 1.93s.** TypeScript clean. New routes verified live in the running backend via OpenAPI: PATCH /posts/{id}, POST approve, POST schedule all registered + auth-gated (unauthenticated returns 403). New frontend routes serve 200: `/scheduled`, `/published`.
- [ ] **Browser e2e** — user-driven check. Approve a draft → click Schedule → pick ~5 min from now → save → status flips to `scheduled`, indigo banner shows, /scheduled page lists it next-up. Reschedule → time updates. /published is empty until Phase 6 lands the publisher.
- [ ] Optimistic UI on approve/schedule (deferred — small enough latency on localhost that the server-roundtrip read is cleaner than rollback complexity)

---

## Phase 6 — Publishing + Scheduler Wiring

Chunked: A (LinkedIn client) → B (publisher orchestration) → C (scheduler wiring + endpoints) → D (e2e smoke).

### Chunk A — LinkedIn HTTP client ✅
- [x] Web-verified current LinkedIn API specs against `learn.microsoft.com/.../li-lms-2026-05` (Posts API, Images API, MultiImage API). Endpoints: `POST /rest/images?action=initializeUpload` → returns `{uploadUrl, image}`; `PUT {uploadUrl}` with `Content-Type: application/octet-stream` and the raw bytes; `POST /rest/posts` returns `201` with the new URN in the `x-restli-id` response header. Required headers on all calls: `Authorization: Bearer …`, `X-Restli-Protocol-Version: 2.0.0`, `LinkedIn-Version: YYYYMM`, `Content-Type: application/json` (for JSON bodies).
- [x] `app/publishing/linkedin_client.py` — pure-HTTP surface (no DB). `LinkedInAPIError` carries `status` + `body` so the publisher can categorize retryable vs permanent failures. Module-level constants for endpoint URLs and a 30s `HTTP_TIMEOUT`. Two header helpers (`_post_headers`, `_image_init_headers`) so future per-endpoint header tweaks don't leak.
- [x] `escape_commentary(text)` — backslash-escapes LinkedIn little-text reserved chars (`\<>#~_*[](){}@|`). Plain `#hashtag` is left as-is; LinkedIn auto-converts to the `{hashtag|#|x}` template on read per the docs. (The escape is defensive — if the generator ever emits `(` or `@` it won't break parsing.)
- [x] `author_urn(account_kind, member_sub=, org_urn=)` — `personal → urn:li:person:<sub>`, `organization → urn:li:organization:<id>`. Raises `ValueError` on missing fields or unknown kind.
- [x] Image upload primitives — `initialize_image_upload(token, owner_urn) → InitializeUploadResult(upload_url, image_urn, expires_at_ms)`, `upload_image_binary(upload_url, png_bytes)`, and the high-level `upload_image(token, owner_urn, png_bytes) → image_urn` that composes both.
- [x] Post-payload builders — `build_text_post_payload`, `build_image_post_payload(image_urn, alt_text?)`, `build_multi_image_post_payload(images=[(urn, alt?)])` enforcing the LinkedIn 2-20 image constraint. All wrap `_post_envelope` which encodes the shared shape (`visibility=PUBLIC`, `feedDistribution=MAIN_FEED`, `lifecycleState=PUBLISHED`, `isReshareDisabledByAuthor=false`).
- [x] `create_post(token, payload) → urn` — POSTs to `/rest/posts`, expects 201, reads URN from `x-restli-id` response header. Raises `LinkedInAPIError` on non-201 or missing header.
- [x] `refresh_access_token(refresh_token_plain)` re-exports the existing `oauth.refresh_token` so the publisher imports everything LinkedIn-related from one module. `_is_token_stale(expires_at)` with a 5-min refresh lead; tolerates naive datetimes by tagging them UTC.
- [x] Tests: 25 new in `tests/publishing/test_linkedin_client.py` covering escape, author_urn (5), initialize_image_upload (happy + 403 + missing-field), upload_image_binary (PUT shape + failure), composed upload_image (POST-then-PUT order), payload builders (text, image with/without alt, multiImage 2-image happy + too-few + too-many), create_post (URN from header + 422 + missing-header), token staleness (close/far/naive). Real `httpx.AsyncClient` is patched via `httpx.MockTransport` — no network. **Full suite 143 passing in 2.04s.**

### Chunk B — Publisher orchestration ✅
- [x] `app/publishing/publisher.py` — DB-orchestration layer over `linkedin_client`. `publish_post(session, post_id) → Post`. Lifecycle (per CLAUDE.md, no skipping): `{approved | scheduled} → publishing → {published | failed}`. Status flip to `publishing` commits before any HTTP work so a concurrent observer sees the lock.
- [x] `ensure_fresh_token(session, account) → plaintext_token` — decrypts; if `_is_token_stale` returns True and a refresh_token exists, calls `lc.refresh_access_token`, re-encrypts access + (rotated) refresh, persists `expires_at`, returns the new plaintext. No-op for accounts without a refresh token.
- [x] `_select_publish_assets(session, post)` — non-carousel: latest GeneratedAsset. Carousel: contiguous batch of `carousel_slide` assets within a 60s window of the newest, returned slide-1-first. Matches the frontend Phase 4 Chunk G batch detection so what the operator previews in `LinkedInPreview` is what ships.
- [x] `_download_png(public_url)` via httpx (bucket is public; no SDK round-trip needed). Permanent-fail on non-200.
- [x] `_build_commentary(post)` — `hook + \n\n + body + \n\n + #tag #tag`. Prose is passed through `lc.escape_commentary` (defensive against `()` `@` etc.); hashtags appended raw so LinkedIn auto-templates them on read.
- [x] Retry policy: `MAX_ATTEMPTS=3`, exponential backoff (2s, 4s) between attempts. `_classify(LinkedInAPIError)` returns one of `{auth, transient, permanent}`. 401/403 → force-refresh (sets `expires_at = now`) + retry once; subsequent 401/403 → permanent. 429/5xx → transient + backoff. Other 4xx → permanent. One `PublishingLog` row per attempt regardless of outcome (`status=success|failure`, response body truncated to 4 KB, error to 500 chars). Final post.error includes the HTTP status code so the operator dashboard can group failures.
- [x] `_load_personal_account(session)` — MVP single-user lookup (latest `account_kind=personal`). When multi-tenant lands, replace with a `user_id` join from `Post`.
- [x] Tests: 24 new in `tests/publishing/test_publisher.py` — pure helpers (`_build_commentary` escape + tag append + no-tags; `_classify` parameterized across 11 status codes; `_account_author_urn`), `ensure_fresh_token` (fresh decrypts and skips refresh; stale refreshes + re-encrypts + flushes), full `publish_post` orchestration (text-only happy; single-image happy; carousel-multi-upload-each; wrong-status raises; missing post raises; permanent 4xx marks failed after one attempt; transient 429 then 200 succeeds on attempt 2; transient 503 exhausts MAX_ATTEMPTS; auth 401 forces refresh + succeeds on attempt 2). **Full suite 167 passing in 1.94s.** All via `AsyncMock` sessions + monkeypatched HTTP — no DB, no Supabase, no LinkedIn.

### Chunk C — Scheduler wiring + endpoints ✅
- [x] `app/scheduler/jobs.py` — `publish_post_job(post_id: str)` opens its own `AsyncSessionLocal` (jobs run outside FastAPI's session-injected scope) and calls `publish_post`. `publish_job_id(post_id) → "publish:<uuid>"` is the stable per-post job id so reschedule/cancel target the same row. `schedule_publish(scheduler, post_id, run_date)` registers/replaces a `DateTrigger` one-shot with `replace_existing=True` + 1h `misfire_grace_time` so a worker that restarted during the fire window still publishes. `cancel_publish(scheduler, post_id) → bool` removes any pending job for the post. Late-imports `publish_post` inside the job to keep scheduler startup lean.
- [x] `POST /posts/{id}/schedule` now also calls `schedule_publish(get_scheduler(), post.id, sched)` after the DB commit. Reschedule path is idempotent — same `publish:<id>` id with `replace_existing=True` swaps the trigger.
- [x] `POST /posts/{id}/publish-now` — bypasses scheduler. Gates on `status ∈ {approved, scheduled}`, calls `cancel_publish(...)` first so any pending APScheduler one-shot can't double-fire, then runs `publish_post(session, post_id)` inline. Returns refreshed `PostRead` on success; raises 502 with `post.error` on `status=failed` so the UI can show the LinkedIn error inline.
- [x] Frontend `drafts/[id]/page.tsx` — new emerald "Publish now" button on the action bar (enabled when `status ∈ {approved, scheduled}`). One-line `confirm()` gate so the user can't fat-finger a real LinkedIn post. Error surfaced inline below the action bar in a red mono panel. Reuses `apiPost<Post>` like the other transitions. Status badge + action-bar disabled states auto-update from the returned `Post`.
- [x] Removed the "Publishes once the Phase 6 worker is wired" placeholder in the scheduled-banner; now reads "The scheduler will publish to LinkedIn at this time."
- [x] **Full test suite still 167 passing in 2.00s.** Routes verified live via OpenAPI: `/posts/{id}/publish-now` registers. TypeScript clean (`npx tsc --noEmit`).
- [ ] **Browser e2e** — user-driven check. Open an approved post → click Publish now → confirm → ~5-15s later button shows "Published ✓" equivalent (status badge flips, linkedin_urn populates) OR red error panel shows the LinkedIn status code. For the scheduled path: schedule a post 90s out, leave the backend running, watch for the `scheduler.publish.fire` log line + the post.status transitioning automatically.

### Chunk D — End-to-end smoke ✅
- [x] **Publish-now → real LinkedIn post.** Verified live 2026-06-02. Draft → approve → render → Publish now → urn `urn:li:share:7467618890898919424` returned in the `x-restli-id` header, persisted to `posts.linkedin_urn`, post status flipped to `published`. The PNG was fetched from Supabase Storage, uploaded to LinkedIn's DMS endpoint (201), and the post was created via `/rest/posts` (201). Round-trip ~14s from button click to status flip.
- [x] **Scheduled APScheduler fire → real LinkedIn post.** Verified live 2026-06-02. Draft → approve → schedule for ~90s → backend logs showed `scheduler.publish.fire` at the right time → publisher ran → post published. The `publish:<id>` APScheduler job persisted via `SQLAlchemyJobStore` survives backend restart and fires deterministically.
- [x] **Token-refresh path verified as unreachable on a standard LinkedIn dev app.** Forced `expires_at = now() + 1 minute` via SQL → publish-now succeeded but the refresh log lines (`publisher.token.refreshing` / `publisher.token.refreshed`) never appeared. Root cause: `refresh_token IS NULL` on the `linkedin_accounts` row → `ensure_fresh_token` short-circuits before checking staleness. **LinkedIn doesn't issue refresh tokens with just `w_member_social` scope** — that's only granted to apps approved for the Marketing Developer Platform (same legal-entity + manual-review path as Community Management API). The refresh code is correct; it just has nothing to refresh. **Operational reality:** access tokens last ~60 days; at day ~60 the access token dies and the operator must re-run the OAuth flow ("Reconnect LinkedIn") to get a fresh 60-day window. Phase 8 hardening should surface a "token expiring in N days" banner on the dashboard so day-60 isn't a surprise.

---

## Pre-Phase 7 — Auto-polish voice pass ✅

- [x] Wired `voice.polish_voice()` into `run_pipeline()`. New constant `POLISH_ESCALATE_THRESHOLD = 2` in [generator.py](backend/app/intelligence/generator.py). When `strip_ai_tells` reports ≥2 violations, the voiced text is re-run through the fast-model polish pass before Stage 3 extract. Added `test_polish_escalates_only_above_threshold` covering both branches; updated `test_voice_strip_runs_between_stage_2_and_3` to handle the new `polish` stage. 54 intelligence tests passing (was 53).

---

## Phase 7 — Analytics ⏸ DEFERRED (2026-06-02)

**Blocked on LinkedIn scope gating.** Web-verified 2026-06-02 (per CLAUDE.md "always verify third-party APIs" rule) before writing any code:

- `r_member_social` (the READ scope that gates `/rest/socialActions/{shareUrn}` for likes + comments on your own posts) is a **CLOSED permission** in 2026 — LinkedIn isn't accepting new access requests "due to resource constraints." Our app has `w_member_social` (write — what we publish with) and OpenID only.
- Every richer engagement endpoint (impressions, clicks, time-series) lives behind `r_organization_social` / Community Management / Marketing Developer Platform — same legal-entity + manual-review gate that blocks org posting and refresh tokens.
- The only `Default` tier (no approval needed) product that returns post engagement is **Member Data Portability API** — but it's a member-authorized data-export API (returns dumps on a delay), not a live-stats endpoint. Viable as a future Phase 7 substrate; needs its response shape web-verified before scoping.

**Path forward:** request Member Data Portability access in parallel; revisit Phase 7 with a daily-export-driven design if/when it lands. Until then, jump to Phase 8.

Original (deferred) scope, kept for reference:
- [ ] `app/analytics/collector.py` — polls LinkedIn share statistics for recent posts
- [ ] `analytics_collection_job()` — hourly cron
- [ ] `GET /analytics/posts/{id}` endpoint
- [ ] Frontend: `/analytics` page with per-post time-series, top hooks, top categories

---

## Phase 8 — Hardening ✅ (functionally complete; remaining items are vendor-blocked)

### Chunk A — Auth health surface ✅
- [x] **"LinkedIn token expires in N days" banner on dashboard.** [frontend/app/page.tsx](frontend/app/page.tsx) gains a `tokenExpiry(expires_at)` helper + a top-of-dashboard banner. Three tiers driven off `expires_at` from `/auth/linkedin/status` (no backend change needed — that field was already returned in Phase 1):
  - silent when > 10 days remain
  - amber ("expires in N days") at ≤ 10 days, with a yellow Reconnect CTA
  - red ("expires in N days" or "expired N days ago") at ≤ 3 days or already past, with a red Reconnect CTA + copy explaining standard dev apps don't issue refresh tokens (so the day-60 manual re-OAuth is the reality, not a bug).
- [x] **Prominent Reconnect button.** The banner's button is the new primary affordance; the existing small underline "Reconnect" inside the LinkedIn section stays as the always-available secondary path. Both call `connect()` → `/auth/linkedin/start`.
- [x] **Duplicate `linkedin_accounts` cleanup — N/A.** The initial schema migration (`ba1ce855d31a_initial_schema.py:160`) already enforces `UniqueConstraint('user_id', 'account_kind', name='uq_linkedin_accounts_user_kind')`, so true duplicates can't exist. Cross-user rows from dev testing are independent rows, not duplicates — leaving them alone (destructive cleanup not justified for MVP).
- [x] TypeScript clean (`npx tsc --noEmit`).
- [ ] **Browser e2e** — user-driven check. Force `expires_at` in Supabase to `now() + 2 days` → red banner with red Reconnect CTA. Set to `now() + 8 days` → amber banner. Set to `now() - 1 day` → red "expired" banner.

### Chunk B — Failure surfacing ✅
- [x] Backend: `GET /posts/{id}/logs` returns all `PublishingLog` rows for a post, newest-first. `PublishingLogRead` exposes `attempt`, `status`, `error`, `linkedin_response`, `attempted_at`.
- [x] Backend: `POST /posts/{id}/retry` resets a `failed → approved` post (clears `post.error`, commits) then re-runs `publish_post` inline. 409 if status isn't `failed`; 502 on a fresh failure. The publisher's own `{approved, scheduled}` lifecycle gate is preserved — retry can't bypass it, it just flips status first.
- [x] Frontend `/drafts/[id]`: when `post.status === 'failed'`, renders a red panel with the error message + a prominent **Retry publish** button + collapsible **Attempt history** showing each publishing_logs row (attempt #, status, timestamp, error). The tiny `Error: …` line on the metadata card is gone; replaced by a `LinkedIn URN` row when published.
- [x] Logs auto-fetch when `post.status ∈ {failed, published, publishing}`; silently no-op otherwise.
- [x] TypeScript clean; backend test suite **168 passing**.
- [ ] **Browser e2e** — user-driven check. Force a failure (e.g., revoke the LinkedIn token in Supabase, click Publish now) → red panel shows with `post.error` + Retry button + attempt log. Fix the token, click Retry → status flips to `published`.

### Chunk C — Resilience ✅
- [x] **APScheduler restart-survival verified live 2026-06-02.** Smoke: scheduled a post 3 min out, killed uvicorn, waited 30s, restarted. `scheduler.started jobs=['publish:03aad8d7-…', 'retrieval']` confirmed the `SQLAlchemyJobStore` rehydrated the one-shot. Job fired on time (`scheduler.publish.fire` at 17:58:00 UTC), LinkedIn returned 201, post status flipped to `published` automatically.
- [x] **Full pipeline smoke verified live 2026-06-02.** Trends refresh → draft generation → render → approve → schedule → APScheduler fire → published — all green on a fresh run.
- [ ] Token-refresh edge cases tested (expired token, revoked grant) — only meaningful once we have a refresh token to test with (requires Marketing Developer Platform approval). Permanently deferred.

### Chunk D — Polish ✅
- [x] **README rewritten.** Reflects Phase 6 / 8 state, lists each subsystem with a status column, fixes the Quick Start bug (no root `.env` — backend reads `backend/.env`, frontend reads `frontend/.env.local`). Adds an "Operational Reality Check" callout for the 60-day LinkedIn token cycle, Phase 7 deferral, and Community Management gating.

### Chunk H — Carousel slide-order fix + URN-encoding fix ✅ (2026-06-03)
- **URN-encoding bug:** `GET /rest/documents/{urn}` returned 400 because LinkedIn's Rest.li requires URL-encoded URNs in path keys (colons → `%3A`). Docs example shows it unencoded but the actual endpoint rejects that. Fixed in [`get_document_status`](backend/app/publishing/linkedin_client.py) via `urllib.parse.quote(..., safe="")`.
- **Slide-order bug:** PDF carousels published in reverse (3/3, 2/3, 1/3). Root cause: `TimestampMixin.created_at` uses Postgres `server_default=func.now()`, which in a single transaction resolves once at transaction start. All three carousel slides got identical `created_at`, so `order_by(created_at.desc())` returned them in implementation-defined order and the publisher's subsequent `batch.reverse()` flipped that into the wrong order.
- **Fix:** new nullable `GeneratedAsset.slide_index` column (Alembic migration `559724258d97_add_slide_index_to_generated_assets.py`). [`render_post_carousel`](backend/app/rendering/renderer.py) now sets `slide_index=i` on every carousel asset (1-based). [`_select_publish_assets`](backend/app/publishing/publisher.py) replaces the `batch.reverse()` with `batch.sort(key=lambda a: a.slide_index or 0)` — authoritative ordering, no clock-reliance. Single-image renders leave `slide_index=NULL`; the column is purely informational outside the carousel path.
- Legacy carousel assets in the DB have `slide_index = NULL` (no info encoded in their rows). They'd publish in unstable order if used; re-render any carousel draft you want to publish to get the proper indexing. (Also re-renders pick up the [Chunk G](#) safe-zone template fix in the same step.)
- Backend suite **172 passing**.

### Chunk G — Native LinkedIn carousel via Documents API ✅ (2026-06-03)
- **Why:** MultiImage posts render as a 1+N image grid on LinkedIn, not a swipeable carousel — and LinkedIn's grid layout aggressively crops each tile, clipping text on the slides we ship. The real native swipeable carousel is a **Document post** (PDF → `/rest/documents` + `/rest/posts` with `content.media`).
- **Web-verified the Documents API** at learn.microsoft.com (li-lms-2026-05): `POST /rest/documents?action=initializeUpload` returns `{uploadUrl, document, uploadUrlExpiresAt}`; PUT the PDF bytes to uploadUrl; poll `GET /rest/documents/{urn}` until `status=AVAILABLE` (LinkedIn explicitly does NOT support SYNCHRONOUS_UPLOAD here); then `POST /rest/posts` with `content.media.{id, title}`. `w_member_social` scope is sufficient for person-owned documents.
- **`img2pdf==0.6.3`** added to [requirements.txt](backend/requirements.txt) (lossless PNG → PDF, no re-encoding). Web-verified latest stable.
- **New module [`app/rendering/pdf.py`](backend/app/rendering/pdf.py)** — single public `build_pdf(pngs) -> bytes` that runs the CPU-bound assembly in `asyncio.to_thread` to keep the event loop free.
- **Extended [`linkedin_client.py`](backend/app/publishing/linkedin_client.py)** with `initialize_document_upload`, `upload_document_binary`, `get_document_status`, `wait_for_document_available` (2s interval, 90s timeout), `upload_document` (composed init+upload+poll), and `build_document_post_payload`. Status-transition errors propagate as `LinkedInAPIError` so existing retry/classification works unchanged.
- **`publisher._attempt_publish` multi-asset branch rewritten** — assets with len ≥ 2 → download all PNGs → assemble PDF → `lc.upload_document` → `build_document_post_payload`. Every slide's `GeneratedAsset.linkedin_asset_urn` gets stamped with the same document URN so the dashboard can trace which document any slide belongs to.
- **[carousel_slide.html](backend/app/rendering/templates/carousel_slide.html) safe-zone fix** — outer 1200×1200 canvas now centers an 840×1080 inner content box. text-6xl → text-5xl. Heads will fit inside the safe area even after aggressive downstream cropping.
- **Tests:** `test_publish_post_multi_image_uploads_each` → renamed `test_publish_post_multi_slide_uploads_document`, asserts the document path (no image uploads, PDF builder called once, document upload called once, every asset row gets the document URN). Patched fixture now stubs `pdf_assembler.build_pdf` + `lc.upload_document`. Backend suite **172 still passing**.

### Chunk F — Carousel publish fix + slide-count variance ✅ (2026-06-02)
- **Bug:** publishing a carousel-rendered post shipped only slide 1 to LinkedIn unless `post.category == carousel`. The frontend's "Render carousel" button works on any post (it dispatches on the chosen template, not the category), so any carousel rendered via the template dropdown on a non-carousel post published as single-image.
- **Fix:** [`publisher._select_publish_assets`](backend/app/publishing/publisher.py) now detects a carousel by asset shape, not by post category — front-of-list cluster of `carousel_slide` assets within `CAROUSEL_BATCH_WINDOW_SECONDS` with ≥ 2 entries → multi-image; otherwise → single asset. Mirrors the frontend `currentCarousel` memo so what the operator previews is what ships. `PostCategory` import dropped (no longer needed).
- **Stage 4 prompt tweak:** carousel_slides instruction reworded from "An array of 3 to 5 slides" → "Default to 3 slides; only add a 4th or 5th if the post genuinely contains that many distinct beats worth their own slide. Do NOT pad to hit 4 or 5." Should reduce the always-4 default toward content-matched counts.
- Backend suite still 172 passing.

### Chunk E — Hook + tag duplication fix ✅ (added 2026-06-02 mid-Phase-8)
- **Bug:** the live LinkedIn post showed the hook twice and hashtags twice. Root cause was a contract mismatch: Stage 3's extract prompt told the LLM `"body": the FULL post text including the hook, verbatim`, so `body` carried the hook + trailing `#tag #tag` line. Then `_build_commentary` composed `hook + body + tag_line` — both leaked twice. The LinkedIn preview happened to render `body + tags` (no hook prepended) so the preview *also* disagreed with what shipped.
- **Fix (defense in depth, both sides):**
  - **Stage 3 prompt** (`generator._EXTRACT_SYSTEM`) updated to require `body` exclude the hook and any trailing hashtag line, with an explicit warning that including them causes duplication on render.
  - **`generator.clean_body(hook, body)`** — idempotent deterministic helper that strips a leading duplicate hook line (case-insensitive, whitespace-tolerant) + trailing hashtag-only lines. Applied inside `_parse_extract` so new drafts persist clean.
  - **`publisher._build_commentary`** now runs `clean_body` before composition, so legacy drafts (where `body` still has the hook + tags inline) publish cleanly without re-generation.
  - **`LinkedInPreview`** now takes a `hook` prop and renders `hook + "\n\n" + body` so the preview matches the live post exactly.
- **Tests:** 2 generator tests updated to the new body shape; 2 new generator tests for the leading-hook-strip and trailing-hashtag-strip; 2 new publisher tests proving `_build_commentary` deduplicates legacy bodies. **Backend suite 172 passing.**
- **Legacy drafts in the DB still have the old body shape** — they publish correctly via the publisher's defensive cleanup, but the dashboard's read-only Body section will still show the duplication until they're regenerated. Acceptable: the data flowing out to LinkedIn is correct; the cosmetic backfill isn't worth a one-shot migration.

---

## Phase 9 — Lifecycle reversals + trend/draft deletion

**Goal:** give the operator flexibility (delete trends, delete drafts, unapprove, unschedule) without breaking the no-skip forward lifecycle in CLAUDE.md. All changes are local-state only — no external surface (LinkedIn, Bluesky, etc.) is mutated by this phase.

**Explicitly out of scope:** deleting published posts from LinkedIn. Discussed and dropped — too risky, low real demand. If it ever becomes needed, it's one new client method + endpoint + a typed-confirmation modal, no schema change.

### Chunk A — Trend deletion
- [x] Backend: `DELETE /trends/{id}` (single) + `POST /trends/bulk-delete` body `{ids: [...]}`.
- [x] Backend: daily sweeper job `cleanup_consumed_trends_job()` registered in [scheduler/jobs.py](backend/app/scheduler/jobs.py) — deletes `trends` rows where `consumed_at < now() - 60 days`. Keeps the table from compounding without touching unconsumed pool.
- [x] Frontend: trash icon per row on `/trends`; multi-select checkbox column + "Delete N selected" CTA in the toolbar.
- [x] Tests: `BulkDeleteRequest` schema validation + sweeper cutoff math ([tests/api/test_trends.py](backend/tests/api/test_trends.py)). Endpoint behavior covered by manual smoke per repo convention.

### Chunk B — Draft deletion + unapprove + unschedule
- [x] Backend: `DELETE /posts/{id}` — gated on `status ∈ {draft, failed}`. Returns 409 with explicit message for `approved`/`scheduled` (operator must reverse lifecycle first). Cascade to `generated_assets` + `publishing_logs` confirmed already present in initial migration; `ai_generations` correctly SET NULL.
- [x] Backend: `POST /posts/{id}/unapprove` — `approved → draft`, no external side effects.
- [x] Backend: `POST /posts/{id}/unschedule` — `scheduled → approved`. Calls `cancel_publish(scheduler, post.id)` from [scheduler/jobs.py](backend/app/scheduler/jobs.py) so the APScheduler one-shot drops cleanly.
- [x] Frontend: contextual buttons on `/drafts/[id]` action bar — "Revert to draft" appears when `status=approved`, "Cancel schedule" appears when `status=scheduled`, "Delete draft" appears when `status ∈ {draft, failed}`. Edit + Schedule buttons re-enable correctly after a revert (driven by `post.status` check that already exists).
- [x] Frontend: hover-trash on `/drafts` list rows, gated by `status ∈ {draft, failed}`.
- [x] Tests: lifecycle gate invariants for all three endpoints ([tests/api/test_posts_lifecycle.py](backend/tests/api/test_posts_lifecycle.py)). Scheduler interaction covered by manual smoke per repo convention.

### Chunk C — E2E verification
- [x] Full reversal loop on a real draft: draft → approve → schedule → unschedule → unapprove → edit → delete. Status badge, action bar, and APScheduler job state all flip correctly at each step.
- [x] Trend delete + sweeper round-trip: 65d-old consumed row swept, fresh unconsumed + 5d-old consumed preserved (verified inline against dev DB on 2026-06-11).
- [x] Bulk-delete UI on `/trends`: select 5 rows → delete → list re-fetches → all 5 gone.

---

## Phase 10 — AI image generation add-on

**Goal:** add a second renderer backend (diffusion via API) alongside the existing Playwright template path. Templated cards stay primary (on-brand per CLAUDE.md). AI image is opt-in per render — operator picks "AI image (Flux)" from the same template dropdown that already exists.

### Chunk A — Renderer abstraction
- [x] Alembic: `generated_assets.render_kind` enum (`'template'`, `'ai_image'`); default `'template'` for all existing rows. _(migration `8a3180a8960e`, applied)_
- [x] Refactor [rendering/renderer.py](backend/app/rendering/renderer.py): split into `_render_template(...)` (current path) and `_render_ai_image(...)` (stub raising NotImplementedError until Chunk B+D). Public `render_post(...)` gains `kind: RenderKind = RenderKind.template`.
- [x] New module `app/rendering/ai_image/` with `interface.py` exposing `ImageGenerator` ABC (`async def generate(prompt: str) -> bytes`).

### Chunk B — Two adapters (Cloudflare primary, Pollinations fallback)
- [x] **Web-verify** both endpoints + response shapes against current docs before code (CLAUDE.md rule). Confirmed: model ID `@cf/black-forest-labs/flux-1-schnell`, endpoint `/accounts/{id}/ai/run/{model}`, response `{result.image: base64}`; Pollinations `image.pollinations.ai/prompt/{q}?model=flux` returns raw image bytes.
- [x] `app/rendering/ai_image/cloudflare.py` — FLUX-1-schnell via Workers AI REST. Free 10k neurons/day (~260 images). Env vars `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_AI_TOKEN` already in `backend/.env.example`. Config knobs: `AI_IMAGE_MODEL`, `AI_IMAGE_STEPS=4`, `AI_IMAGE_TIMEOUT_SECONDS=30`.
- [x] `app/rendering/ai_image/pollinations.py` — GET-URL Flux call, no auth. Validates `content-type: image/*` to detect HTML error pages.
- [x] `app/rendering/ai_image/__init__.py` — `generate_image(prompt, primary=?, fallback=?)` composer: try Cloudflare, on any exception (including `CloudflareConfigError`) fall back to Pollinations. Logs `ai_image.primary_failed` + `ai_image.fallback_used`.
- [x] Tests: 12 tests in `tests/rendering/test_ai_image.py` — Cloudflare happy/missing-creds/HTTP-error/success-false/missing-image; Pollinations happy/non-image/HTTP-error; composer primary-ok/primary-http-fail/primary-config-fail/both-fail.

### Chunk C — Stage 5 visual-prompt extraction
- [x] Added Stage 5 to `generator.run_pipeline()` — FAST model `llama-3.1-8b-instant`, JSON output, temp 0.4, 200 max_tokens. Returns one 12-25 word visual prompt aligned with the [[project_visual_style]] minimal-dark brand identity.
- [x] Persists to `Post.extracts.ai_image_prompt` (no new column; JSONB already absorbs new fields).
- [x] Lazy backfill: `_ensure_ai_image_prompt(session, post)` runs Stage 5 inline and writes onto `post.extracts` for any pre-Phase-10 post on first AI-image render. Same shape as Stage 4 lazy-extract.
- [x] Cost target: <$0.0002/post on `llama-3.1-8b-instant` (200 max_tokens × $0.05/1M = ~$0.00001). Well under budget.
- [x] Tests: 9 new — `_parse_ai_image_prompt` (well-formed / bad JSON / non-dict / missing key / empty / whitespace), `extract_ai_image_prompt` (happy path / bad JSON fallback / empty fallback). `run_pipeline.test_full_five_stage_flow` updated to assert all 5 stages in order with right models.
- [x] Brand-safe fallback `_AI_IMAGE_PROMPT_FALLBACK` ("minimalist editorial illustration on a near-black background…") used when Stage 5 emits unparseable or empty output, so the renderer always has a usable prompt.

### Chunk D — Brand-wrap composite
- [x] New HTML template `backend/app/rendering/templates/ai_image_wrap.html` — eyebrow + centered 800×800 AI image inset (ring + rounded) + brand strap inside a 1200×1200 black canvas. Matches [[project_visual_style]] minimal-dark identity.
- [x] Migration `3b27fdcf2346` — adds `'ai_image'` value to `template_category` enum + seeds the `ai_image_wrap` row in `templates`. Idempotent (ON CONFLICT, ADD VALUE IF NOT EXISTS, COMMIT before ALTER TYPE).
- [x] `_render_ai_image` end-to-end: lazy Stage-5 prompt resolve → `generate_image()` (Cloudflare → Pollinations) → base64 data URI → Jinja2 render `ai_image_wrap.html` → Playwright PNG → Supabase upload → `GeneratedAsset` row with `render_kind=ai_image`.
- [x] API: `RenderRequest.kind: RenderKind` (default `'template'`); `POST /posts/{id}/render` passes `kind` through. `GeneratedAssetRead.render_kind` exposed so frontend can label assets.
- [x] Tests: 2 new Jinja2 renders (brand-wrap happy + HTML-escape on hook). Suite at 209.

### Chunk E — UI + smoke
- [x] Drafts detail template dropdown gains "✦ AI image (Flux)" option above the regular template list. `ai_image_wrap` is filtered out of the regular list (operator picks it indirectly via the AI option). Sentinel value `__ai_image__` triggers `kind: "ai_image"` on `/render`; carousel branch + slide index are bypassed.
- [x] Asset metadata + earlier-renders thumbnails show a violet "AI image" badge when `render_kind === "ai_image"`, so both styles read clearly side-by-side.
- [x] **Manual E2E #1**: render templated card → swap to AI image → new asset appears with violet "AI image" badge. Earlier-renders strip shows both styles. _(PASS, 2026-06-13)_
- [x] **Manual E2E #2**: publish a draft whose latest asset is an AI image — confirm the brand-wrap composite ships and renders cleanly on the actual LinkedIn post. _(PASS, 2026-06-13)_

---

## Phase 11 — Multi-platform publishing (Bluesky, Mastodon, Threads, Instagram)

**Goal:** end the LinkedIn-only assumption. Same draft fans out to multiple selected platforms via the `Publisher` ABC. Threads + Instagram ship code-complete but stay behind feature flags until Meta App Review clears (precedent: [[project_linkedin_org_posting]]).

**Scope:** single phase, four chunks. Each chunk plugs into the abstraction landed in Chunk A.

### Chunk A — Abstraction refactor + Bluesky publisher
- [x] Alembic: new `post_targets` table — `(id, post_id, platform, status, external_urn, scheduled_at, published_at, error, raw_request)`. `posts` keeps draft content; `post_targets` is per-platform fan-out. _(c9e1f02db4a7 applied 2026-06-15 — 12 LinkedIn rows backfilled from published/failed/scheduled posts.)_
- [x] `posts.linkedin_urn` → deprecated in favor of `post_targets.external_urn`. Column kept nullable + still stamped from the first LinkedIn target for one release. Removal slated for Phase 12 cleanup.
- [x] `Publisher` ABC formalized in [publishing/base.py](backend/app/publishing/base.py); `LinkedInPublisher` extracted into [publishing/linkedin.py](backend/app/publishing/linkedin.py). Old `publishing/publisher.py` deleted.
- [x] `BlueskyPublisher` — AT Protocol via `atproto==0.0.62` (pre-1.0, exact pin). **App-Password auth, not OAuth** — atproto Python SDK is still session-based pre-1.0; OAuth migration deferred. Posts to `app.bsky.feed.post` via `Client.send_post` / `Client.send_images`. 300-char limit + 4-image cap (orchestrator gates char_limit, BlueskyPublisher truncates carousel slides ≥5).
- [x] Connect flow: `POST /auth/bluesky/connect` + `GET /auth/bluesky/status` + `DELETE /auth/bluesky/disconnect`. No browser redirect — handle + app password go to backend, atproto validates, Fernet-encrypted at rest. New `bluesky_accounts` table mirrors `linkedin_accounts` shape minus token-refresh fields.
- [x] Scheduler: `publish_target_job(target_id)` replaces `publish_post_job(post_id)`. One APScheduler job per target.
- [x] Frontend: per-platform status badge strip (color-coded by `TargetStatus`); Bluesky connect section on dashboard alongside LinkedIn. Approve/schedule/publish-now/retry/unschedule all fan out per-target. _(Platform multi-select moved from approve to /generate page on 2026-06-16 after the first live publish hit Bluesky's 300-char gate. See [[#2026-06-16-phase-11-chunk-a-iteration]] in CONTEXT.md.)_
- [x] **Iteration 2026-06-16:** platform picker moves pre-generation. Generator runs `compress_for_bluesky` inline so each platform ships in its own shape. `PostTarget.commentary` (migration `d4f6b8e1029c`) stores the per-platform rewrite. Dashboard error panel now surfaces per-target errors. +12 tests (compress_for_bluesky happy/empty/over-cap/quote-strip, canonical resolver, build_platform_commentary, orchestrator's target-commentary fallback).
- [x] Tests: 34 new across `tests/publishing/test_orchestrator.py`, `test_linkedin_publisher.py`, `test_bluesky_publisher.py` — char-limit gate, retry classification, account loader, atproto-mocked happy + sad paths, Bluesky carousel truncation. _(220 backend tests passing.)_

### Chunk B — Mastodon publisher ✅ (2026-06-16)
- [x] Per-instance OAuth — user supplies their instance URL (e.g. `mastodon.social`, `hachyderm.io`) on connect; normalized + stored on `mastodon_accounts.instance_url`. New `mastodon_accounts` table (migration `e2a7c4b96d18`, no `expires_at`/`refresh_token` — Mastodon tokens don't expire by default).
- [x] **Federated → dynamic app registration.** `POST {instance}/api/v1/apps` at connect time (no central registry); `client_id`/`client_secret` carried through the Fernet-encrypted OAuth `state` (TTL-checked), so the callback is stateless — no `mastodon_apps` table.
- [x] `MastodonPublisher` ([publishing/mastodon.py](backend/app/publishing/mastodon.py)) — raw httpx (no SDK). Two-step media: `POST /api/v2/media` (multipart, handles 200-sync + 202-async-poll) → `POST /api/v1/statuses` with `media_ids[]` + `Idempotency-Key`. `char_limit=500`, `max_images=4`. Orchestrator wiring: one register-import + one `_load_account` branch.
- [x] OAuth: `/auth/mastodon/start?instance=<url>` + `/callback` + `/status` + `/disconnect` ([api/auth_mastodon.py](backend/app/api/auth_mastodon.py)). Access token Fernet-encrypted at rest. Web-verified API against docs.joinmastodon.org per CLAUDE.md.
- [x] Frontend: Mastodon connect section on the dashboard (instance input → OAuth redirect, status + disconnect); `mastodon` added to the `/drafts` platform multi-select. Per-target status-badge strip from Chunk A renders it automatically.
- [x] **STRICT char-limit (no `compress_for_mastodon`)** per memory [[project-per-platform-generation-strategy]] (user-confirmed). Mastodon targets get `commentary=None` → fall back to LinkedIn-shaped body → trip the 500-char gate loudly until Phase 12's per-platform prompt matrix lands. Intentional pressure, not a bug.
- [x] Tests: 30 new in [tests/publishing/test_mastodon_publisher.py](backend/tests/publishing/test_mastodon_publisher.py) — normalize_instance, state round-trip, register_app/exchange_code/verify_credentials, media sync + async-poll, carousel truncation to 4, error classification (401/403/429/503/422/400), account loader. **Full suite 262 passing.** tsc clean. Migration applied to Supabase; all 4 routes registered.
- [ ] **Live (user-driven):** connect a real Mastodon account via the dashboard → OAuth round-trip → `mastodon_accounts` row. Generate a draft targeting Mastodon → approve → publish-now → confirm the target **fails the 500-char gate** with the clear error (expected until Phase 12). A hand-shortened ≤500-char draft publishes end-to-end.

### Chunk C — Threads publisher (Meta-gated) ✅ (2026-06-16)
- [ ] **Submit Meta App Review in parallel with code.** Two permissions: `threads_basic`, `threads_content_publish`. Per [[project_linkedin_org_posting]] this gate is the same shape — code now, approval later. Pre-approval the publisher works only against the developer + tester accounts in the Meta app. _(User action — code ships ahead of approval.)_
- [x] `ThreadsPublisher` ([publishing/threads.py](backend/app/publishing/threads.py)) — raw httpx, two-step container API. Create container `POST {graph}/{ver}/{user-id}/threads` (media_type TEXT/IMAGE/CAROUSEL), poll the container `status` until FINISHED (media is processed async), then `POST .../threads_publish` with `creation_id`. Carousel = N× `is_carousel_item` IMAGE containers (each polled) → parent CAROUSEL container with `children`. `char_limit=500`, `max_images=20` (carousel 2–20). Threads fetches `image_url` from our public Supabase bucket itself (no byte download). Error classification 401/403→Auth, 429/5xx→Transient, other 4xx→Permanent, **plus** a body sniff for Meta's `OAuthException`/code 190 (returned as 400 for a dead token) → Auth.
- [x] OAuth ([publishing/threads_oauth.py](backend/app/publishing/threads_oauth.py) + [api/auth_threads.py](backend/app/api/auth_threads.py)) — single fixed Meta app (LinkedIn-shaped, not federated). `/auth/threads/start` returns the authorize URL; `/callback` exchanges the code for a **short-lived** token, immediately upgrades to a **60-day long-lived** token (`th_exchange_token`), resolves the profile (`/me`), and persists. `/status` + `/disconnect` round it out. Web-verified endpoints against developers.facebook.com (two sources) per CLAUDE.md.
- [x] **Token refresh is in place, no separate refresh_token.** `threads_accounts` (migration `f1b3d7a8e564`) carries `expires_at` but no `refresh_token` — Threads `GET /refresh_access_token` returns a fresh access token. `ThreadsPublisher._ensure_fresh_token` refreshes proactively when within a 2-day lead of expiry. The orchestrator's forced-refresh-on-401 branch guards on `hasattr(account, "refresh_token")`, so a hard 401 degrades to terminal-after-retries (operator reconnects) — same clean degradation as Mastodon.
- [x] New env var `PLATFORM_THREADS_ENABLED` (default `false`). Backend gates `/auth/threads/start` (503 when off) and `/status` returns `enabled: false`. Frontend uses that `enabled` flag as the source of truth — the dashboard Threads connect section AND the `/generate` platform picker both hide Threads when off (no separate frontend env var).
- [x] Orchestrator/scheduler/posts API needed **zero changes** — `Platform.threads` already existed and the publish/schedule/retry/aggregate paths are platform-agnostic. Wiring was one register-import + one `_load_account` branch.
- [x] Tests: 28 new in [tests/publishing/test_threads_publisher.py](backend/tests/publishing/test_threads_publisher.py) — state round-trip, authorize URL, exchange_code/exchange_long_lived/refresh/fetch_profile, token staleness + proactive refresh, publish text/single-image/carousel/truncate-to-max, container ERROR-status → permanent, error classification (incl. OAuthException-in-400 → Auth), account loader. **Full suite 290 passing.** tsc clean. Migration applied to Supabase; all 4 routes registered.
- [ ] **Live (user-driven, post-approval):** flip `PLATFORM_THREADS_ENABLED=true`, connect a Threads tester account → OAuth round-trip → `threads_accounts` row with a 60-day `expires_at`. Generate a ≤500-char draft targeting Threads → approve → publish-now → confirm the container creates, polls FINISHED, publishes, and the media id lands on the `post_targets` row.

### Chunk D — Instagram publisher (Meta-gated + account conversion) ✅ (2026-06-16)
- [ ] **User converts Instagram → Creator account.** 30 seconds in IG mobile settings, free, reversible. Required because personal IG accounts cannot publish via API (web-verified June 2026). Creator account skips the legacy Facebook Page link requirement. _(User action.)_
- [ ] **Submit Meta App Review** for the Instagram content-publish scopes. Note: the **Instagram Login** flow uses `instagram_business_basic` + `instagram_business_content_publish` (the Facebook-Login variant is `instagram_basic`/`instagram_content_publish`); we use the Instagram-Login naming since that's the mandated flow. Scopes are env-driven (`INSTAGRAM_SCOPES`) so a rename is a one-line change. _(User action — code ships ahead of approval.)_
- [x] `InstagramPublisher` ([publishing/instagram.py](backend/app/publishing/instagram.py)) — raw httpx, two-step container API. Create `POST {graph}/{ver}/{ig-user-id}/media` (single image: `image_url`+`caption`; carousel: N× `is_carousel_item` image containers → parent `media_type=CAROUSEL`+`children`), poll the container `status_code` until FINISHED, then `POST .../media_publish` with `creation_id`. **No text-only post** — empty assets → `PermanentPublishError` (IG requires media, unlike Threads). `char_limit=2200`, `max_images=10` (carousel 2–10). IG fetches `image_url` from our public Supabase bucket itself. Error classification mirrors Threads (401/403→Auth, 429/5xx→Transient, other 4xx→Permanent, + OAuthException/code-190 body sniff → Auth).
- [x] OAuth ([publishing/instagram_oauth.py](backend/app/publishing/instagram_oauth.py) + [api/auth_instagram.py](backend/app/api/auth_instagram.py)) — Meta's **Instagram Login** flow (NOT Facebook Login — the lightweight path that skips the Facebook-Page link). `/auth/instagram/start` returns the authorize URL; `/callback` exchanges the code for a short-lived token (+ IG-scoped `user_id`, used as the publish path segment), upgrades to a 60-day long-lived token (`ig_exchange_token`), resolves the profile (`/me?fields=user_id,username,account_type`), and persists. `/status` + `/disconnect` round it out. Code-exchange body handles both flat `{access_token,user_id}` and wrapped `{data:[…]}` shapes. Web-verified against developers.facebook.com (two sources) per CLAUDE.md.
- [x] **Token refresh is in place, no separate refresh_token** (same as Threads). `instagram_accounts` (migration `a3c8e0f5471b`) carries `expires_at` but no `refresh_token` — `GET /refresh_access_token?grant_type=ig_refresh_token` returns a fresh access token. `InstagramPublisher._ensure_fresh_token` refreshes proactively inside a 2-day lead; the orchestrator's forced-refresh-on-401 guard (`hasattr(account,"refresh_token")`) degrades a hard 401 to terminal-after-retries.
- [x] New env var `PLATFORM_INSTAGRAM_ENABLED` (default `false`). Backend gates `/auth/instagram/start` (503 when off) and `/status` returns `enabled:false`. Frontend uses that `enabled` flag as the source of truth — the dashboard Instagram connect section AND the `/generate` platform picker both hide Instagram when off (no separate frontend env var).
- [x] Orchestrator/scheduler/posts API needed **zero changes** — `Platform.instagram` already existed; wiring was one register-import + one `_load_account` branch.
- [x] Tests: 30 new in [tests/publishing/test_instagram_publisher.py](backend/tests/publishing/test_instagram_publisher.py) — state round-trip, authorize URL, exchange_code (flat + wrapped body + missing-fields), long-lived/refresh/profile (incl. legacy `id` field), token staleness + proactive refresh, **publish requires-image gate**, single-image (asserts no `media_type`, `caption` param), carousel (`ITEM1,ITEM2,ITEM3`), truncate-to-max, container ERROR `status_code` → permanent, error classification (incl. OAuthException-in-400 → Auth), account loader. **Full suite 320 passing.** tsc clean. Migration applied to Supabase; all 4 routes registered.
- [ ] **Live (user-driven, post-approval):** convert to Creator account, flip `PLATFORM_INSTAGRAM_ENABLED=true`, connect via Instagram Login → `instagram_accounts` row with a 60-day `expires_at`. Generate a draft targeting Instagram, **render a card** (IG requires an image), approve → publish-now → confirm the container creates, polls FINISHED, publishes, and the media id lands on the `post_targets` row.

### Chunk E — Per-platform preview + E2E ✅ (2026-06-16)
- [x] New generic [PlatformPreview.tsx](frontend/components/PlatformPreview.tsx) — platform tab strip across the draft's targets, dispatching to per-platform card variants: LinkedIn reuses the existing rich `LinkedInPreview`; Bluesky/Mastodon/Threads share a text-first `MicroblogCard` (platform-accented handle + hashtags + single-image hang); Instagram gets an image-first `InstagramCard` that **flags the no-image case** (IG can't post text-only — surfaces the would-be publish-gate failure inline). Not pixel-perfect by design. Wired into [drafts/[id]/page.tsx](frontend/app/drafts/[id]/page.tsx) replacing the LinkedIn-only block; reads each target's `commentary` (per-platform rewrite) or falls back to the canonical hook+body+tags.
- [x] Inline char-limit warning: `PLATFORM_LIMITS` mirrors each `Publisher.char_limit` (LinkedIn 3000, Bluesky 300, Mastodon/Threads 500, Instagram 2200). Live char count per tab; over-cap shows an amber banner naming the cap + that the long-term fix is per-platform generation (Phase 12), not truncation, and notes when the target is falling back to the LinkedIn-shaped body.
- [x] **Code-level E2E** ([tests/publishing/test_orchestrator.py](backend/tests/publishing/test_orchestrator.py) `test_fan_out_persists_distinct_urns_per_platform`): one draft → LinkedIn + Bluesky targets → each publishes via its own publisher and persists a **distinct** `external_urn`, proving the fan-out + per-target persistence are platform-independent. Suite 321 passing, tsc clean.
- [x] **Live E2E (user-driven):** one draft → target LinkedIn + Bluesky simultaneously → approve → publish-now → both URNs persist on their respective `post_targets` rows; both posts go live. _(Requires real connected accounts — goes live, can't run from CI.)_
- [ ] **Live E2E (Meta-gated, user-driven):** same draft against Threads/Instagram (tester accounts, pre-approval) → publishes against the Meta dev sandbox once the flags are flipped + App Review clears.

---

## Phase 12 — Categories expansion + per-platform prompt matrix + fresh feeds

**Goal:** widen content surface. 4 new categories with seeded prompts. Restructure `prompts` for (category × platform) matrix so the same draft category produces a long LinkedIn post, a 280-char Bluesky line, a 500-char Threads post, etc. Add 1–2 RSS feeds aimed at the new categories — **freshness gate is non-negotiable: any new feed must be publishing in 2026 and posting at least monthly, otherwise it's cut.**

### Chunk A — Prompt matrix refactor ✅ (2026-06-16)
- [x] Alembic (`b7d3a1c8e92f`): `prompts.platform` enum column (reuses the existing `platform` enum type, nullable for "any/legacy"). Existing 4 rows backfilled to `platform='linkedin'`. New unique constraint `uq_prompts_name_platform_version` `(name, platform, version)`. Applied to Supabase.
- [x] Matrix lookup: `_load_active_prompt(session, category, platform)` prefers the per-platform variant, falls back to `platform IS NULL`, raises if neither. Canonical pipeline loads `platform='linkedin'`. New `_load_platform_prompt` (exact-platform, no NULL fallback) drives the per-target commentary rewrite.
- [x] Stage-2 per-platform rewrite is now **DB-driven** via `run_platform_rewrite` (replaces the hardcoded `compress_for_bluesky` inline stopgap per memory [[project-per-platform-generation-strategy]]). `_build_platform_commentary` loads the per-platform prompt; LinkedIn → None (canonical Post); no-prompt fallbacks: Bluesky → legacy `compress_for_bluesky`, Mastodon/Threads/Instagram → None (trips char-gate loudly until seeded). Per-platform tone (LinkedIn 140–220w / Bluesky ≤280 / Threads ≤500 conversational / Mastodon ≤500 engineering / Instagram hashtag-heavy caption) lives in the **seeded prompt bodies** (Chunk B). Over-cap output is NOT truncated — loud gate failure is the signal to fix the prompt.
- [x] Tests: 12 new (`tests/intelligence/test_prompt_matrix.py` + updated `TestBuildPlatformCommentary`) — matrix prefer-platform, NULL fallback, platform=None skip, raise-when-neither, exact `_load_platform_prompt`, `PLATFORM_CHAR_LIMITS` map, rewrite within-cap / no-truncate-over-cap / Instagram long-caption. 333 backend tests passing.

### Chunk B — 4 new categories with seeded prompts ✅ (2026-06-17)
- [x] `dev_tooling` — anchors: Will Larson (internal platforms as products), Gergely Orosz / Pragmatic Engineer (DORA over LOC)
- [x] `pricing_business_model` — anchors: Ben Thompson / Stratechery (aggregation, free tiers), Stripe (usage-based pricing)
- [x] `product_postmortem` — anchors: rachelbythebay-style blameless incident writeups (root cause is the system, rehearse the failure)
- [x] `design_thinking` — anchors: Julie Zhuo (design = decisions), NN/g (research before pixels)
- [x] Alembic migration `c5f9a26b81e4` seeds each — 4 categories × 5 platforms = **20 prompt rows**, all v1, all `is_active=true`. Verified live (20 rows, 5 per category, all platforms, all active). The LinkedIn variant is a Stage-1 angle/writer prompt (long-form founder voice, v4 shape); the Bluesky/Threads/Mastodon/Instagram variants are Stage-2 **rewrite** prompts with a per-platform anchor honoring that platform's char budget. Enum prerequisite handled: the 4 new `post_category` values are added inside an `autocommit_block` so the seed INSERTs can reference them (Postgres same-transaction restriction).
- [x] Drafts UI category dropdown grows from 4 to 8 (`GENERATABLE`). `PostCategory` type union + `CATEGORY_LABEL` + `CATEGORY_COLORS` extended across all 4 pages that render category chips (drafts, drafts/[id], scheduled, published) so tsc stays green. tsc exit 0.
- [x] **Follow-up (2026-06-17, migration `e8b4c1f7d320`):** backfilled the 16 missing per-platform rewrite prompts for the original 4 categories (founder_insight/engineering_lesson/ai_automation/startup_opinion × bluesky/threads/mastodon/instagram) reusing their v4 anchor voices. All 8 generatable categories now uniform on the matrix → **40 active prompt rows** (8 × 5). `compress_for_bluesky` demoted to pure safety net. (`technical_humor`/`carousel` remain prompt-less + absent from `GENERATABLE` — latent, not reachable.)

### Chunk C — Fresh RSS additions ✅ (2026-06-17)
- [x] **Web-verified each candidate feed live (2026-06-17)** per CLAUDE.md. Survivors fetched + confirmed publishing in 2026.
- [x] Verified + added (3): **Lethain.com** `https://lethain.com/feeds/` (newest 2026-06-15), **Julia Evans** `https://jvns.ca/atom.xml` (newest 2026-05-15), **NN/g** `https://www.nngroup.com/feed/rss/` (newest 2026-06-12). **Cut (2):** rachelbythebay — blocks non-browser bots (404 to our UA on both feed + site; our retrieval bot can't read it); a16z `/feed/` — 404 + duplicates the Stratechery/Stripe business/pricing coverage already in the list.
- [x] Per-feed 25-cap + 90-day age cutoff already in place — no new code. Freshness gate enforced by retrieval.

### Chunk D — UI + activation ✅ (2026-06-17)
- [x] Category dropdown extended (Chunk B); per-platform previews from Phase 11 Chunk E automatically consume the right prompt variant — `PlatformPreview` reads each target's `commentary`, which now comes from the DB matrix. No code change needed.
- [x] **E2E freshness check (run live):** fetched the 3 new feeds → 27 items within the 90-day cutoff, **11 within 30 days** (Lethain 06-15, NN/g 06-12/06-05, etc.). New sources return recent `fetched_at`. ✅
- [ ] **E2E matrix smoke (user-driven, live):** generate `dev_tooling` for Bluesky → short punchy output; same category for LinkedIn → 140–220-word post. Needs live Groq tokens + trends in the pool; the matrix *dispatch* is proven at the code level (`test_prompt_matrix.py` + `TestBuildPlatformCommentary`), the subjective output-length check goes live with a real generation.

### Chunk E — Custom categories (deferred)
- [ ] Admin UI for runtime-defined categories is **deferred to a future Phase 13** if real demand surfaces. Seeded-via-migration keeps voice quality controlled by anchor examples; a free-form UI risks generic AI-spam output (violates CLAUDE.md philosophy). No schema change needed later — prompts table is already data-driven, so when/if this lands it's a UI + write endpoint, not a refactor.

---

## Blockers

- **Reddit Data API access** — submitted to Reddit, awaiting approval. Phase 2 Reddit fetcher is written (`app/retrieval/reddit.py`) but stays out of the orchestrator's enabled fetcher list until approval. Activation = one-line import change in `orchestrator.py`. RSS + HackerNews carry the MVP until approval.

---

## Technical Debt

(None yet.)

---

## Discovered Tasks (added as work progresses)

- [x] **Bluesky hashtag facets (2026-06-17).** `#tags` in Bluesky posts were inert plain text — atproto needs `app.bsky.richtext.facet#tag` facets. `bluesky._build_richtext` now rebuilds the commentary through `client_utils.TextBuilder` so the generated tags are real/clickable. Mastodon/Instagram/LinkedIn parse or auto-link hashtags natively, so no change needed there. +5 tests (338 total).
- [ ] **Threads hashtag behavior (deferred, Meta-gated).** Worth confirming when Threads goes live whether its API auto-links hashtags from `text` or needs a `topic_tag`-style field; if the latter, mirror the Bluesky facet approach in the Threads publisher.
