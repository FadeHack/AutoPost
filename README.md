# AutoPost

AI-powered social content automation, internal-first.

Pulls fresh tech / startup / AI trends from RSS + HackerNews, generates founder-voice drafts with Groq, renders branded visuals from HTML / Tailwind templates via headless Chromium, and fans the same draft out to multiple social platforms on schedule — with human-in-the-loop approval at every step.

---

## What works today

The end-to-end pipeline is shipped through **Phase 12**. LinkedIn and Bluesky publish live today; Mastodon is code-complete pending a live account connect; Threads and Instagram ship code-complete behind feature flags awaiting Meta App Review.

| Phase | Subsystem | Status |
|------|-----------|--------|
| 1 | Schema + Supabase Auth + LinkedIn OAuth | done |
| 2 | Retrieval (10 RSS feeds + HackerNews + APScheduler cron) | done |
| 3 | Intelligence (4-stage Groq pipeline + voice filter + DB-versioned prompts) | done |
| 4 | Rendering (5 Tailwind templates + Playwright + Supabase Storage CDN) | done |
| 5 | Dashboard (drafts queue, edit, approve, schedule, queue pages) | done |
| 6 | Publishing (LinkedIn `/rest/posts` + image upload + APScheduler one-shots) | done |
| 7 | Analytics | **deferred** — LinkedIn `r_member_social` is closed in 2026 |
| 8 | Hardening (token-expiry banner, failure surfacing + retry, restart smoke) | done |
| 9 | Lifecycle reversals + trend / draft deletion | done |
| 10 | AI image generation add-on (secondary visual path) | done |
| 11 | Multi-platform fan-out (Bluesky, Mastodon, Threads, Instagram) | done |
| 12 | Categories expansion (8 categories) + per-platform prompt matrix + fresh feeds | done |

See [`CHECKLIST.md`](./CHECKLIST.md) for the full milestone log and [`CONTEXT.md`](./CONTEXT.md) for the architecture + decisions.

---

## Platforms

The same draft fans out to multiple targets via the `Publisher` ABC ([`backend/app/publishing/base.py`](./backend/app/publishing/base.py)). Each draft category produces platform-shaped text through a per-platform prompt matrix — a long LinkedIn post, a ≤300-char Bluesky line, a ≤500-char Threads/Mastodon post, a hashtag-rich Instagram caption.

| Platform | Auth | Char cap | Live? |
|----------|------|----------|-------|
| LinkedIn | 3-legged OAuth, posts as the member | 3000 | ✅ live |
| Bluesky | AT Protocol app password (`atproto`) | 300 | ✅ live (hashtags promoted to real facets) |
| Mastodon | Per-instance dynamic OAuth | 500 | code-complete, pending live connect |
| Threads | Meta OAuth (60-day long-lived token) | 500 | code-complete, behind `PLATFORM_THREADS_ENABLED` |
| Instagram | Meta Instagram-Login OAuth | 2200 | code-complete, behind `PLATFORM_INSTAGRAM_ENABLED` (image required) |

Posts move through one status lifecycle only: `draft → approved → scheduled → publishing → (published | failed)`. Per-platform fan-out state lives on `post_targets`; the canonical draft is LinkedIn-shaped, and each target carries its own rewritten `commentary`.

---

## Content categories

8 generatable categories, each seeded with versioned anchor-voice prompts across all 5 platforms (40 active prompt rows):

`founder_insight` · `engineering_lesson` · `ai_automation` · `startup_opinion` · `dev_tooling` · `pricing_business_model` · `product_postmortem` · `design_thinking`

Prompts live in the `prompts` table (versioned, never hardcoded), keyed `(name, platform, version)`. The LinkedIn variant is a Stage-1 writer prompt; the other platforms are Stage-2 rewrite prompts honoring each platform's char budget. Over-cap output is **never silently truncated** — it trips a loud gate so the prompt gets fixed, not the post mangled.

---

## Repo Layout

```
AutoPost/
├── CLAUDE.md          rules + guardrails (auto-loaded by Claude)
├── CONTEXT.md         persistent engineering memory (what & why)
├── CHECKLIST.md       milestone tracking
├── INSTRUCTIONS.md    operational how-to (setup / run / debug)
├── backend/           FastAPI + SQLAlchemy + APScheduler + Playwright
│   ├── .env           backend secrets (gitignored)
│   └── app/
│       ├── retrieval/      RSS + HackerNews fetchers, dedupe, orchestrator
│       ├── intelligence/   Groq client, prompts, generator, voice filter
│       ├── rendering/      Templates, Playwright runner, Supabase Storage
│       ├── publishing/     Per-platform publishers + OAuth + orchestrator
│       ├── scheduler/      APScheduler (cron + one-shot publish jobs)
│       └── api/            FastAPI routes
└── frontend/          Next.js (App Router) + TailwindCSS + Supabase Auth
    └── .env.local     NEXT_PUBLIC_* values only (gitignored)
```

---

## Read Order

1. [`CLAUDE.md`](./CLAUDE.md) — non-negotiable rules + locked tech choices
2. [`CHECKLIST.md`](./CHECKLIST.md) — what's done, what's next
3. [`CONTEXT.md`](./CONTEXT.md) — architecture + every load-bearing decision
4. [`INSTRUCTIONS.md`](./INSTRUCTIONS.md) — setup, commands, debugging

---

## Quick Start

Full first-time setup lives in [`INSTRUCTIONS.md`](./INSTRUCTIONS.md). Short version:

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env             # then fill in real values
alembic upgrade head             # creates schema in Supabase

# Frontend
cd ../frontend
npm install
cp .env.local.example .env.local # then fill in NEXT_PUBLIC_* values

# Run (two terminals)
cd backend && source venv/bin/activate && uvicorn app.main:app --reload
cd frontend && npm run dev
```

The backend reads its env from `backend/.env`; Next.js reads its env from `frontend/.env.local`. **There is no root `.env`** — see [`CLAUDE.md`](./CLAUDE.md) for the rationale (backend secrets must not leak to the browser).

---

## Locked Stack

LLM: Groq (`llama-3.3-70b-versatile` primary, `llama-3.1-8b-instant` fast).
DB: Supabase Postgres on the Session Pooler URL (port 5432).
Auth: Supabase Auth on the dashboard; per-platform OAuth / app-password for posting.
Visuals: HTML + Tailwind → PNG via Playwright headless Chromium (diffusion image gen is a secondary path only).
Scheduler: APScheduler in-process, `SQLAlchemyJobStore` for restart survival.

Locked = do not swap without explicit approval. See `CLAUDE.md`.

---

## Operational Reality Check

- **LinkedIn access tokens last ~60 days.** Standard dev apps don't get refresh tokens — refresh is only granted by the Marketing Developer Platform (legal-entity + manual review). The dashboard surfaces an amber banner at ≤10 days, red at ≤3 days, with a "Reconnect LinkedIn" CTA. Plan on re-OAuthing once every two months.
- **LinkedIn Company-Page posting is built but blocked** by LinkedIn-side Community Management API approval (legal entity required). The `account_kind` column + organization branch are wired today; activation = approval, not code.
- **Threads + Instagram are gated behind Meta App Review.** Code is complete and tested against the Meta dev sandbox; flip `PLATFORM_THREADS_ENABLED` / `PLATFORM_INSTAGRAM_ENABLED` once approval clears. Instagram additionally requires a Creator account and always needs an image (no text-only posts).
- **Analytics (Phase 7) is deferred** — `r_member_social` is a closed permission in 2026. Member Data Portability is the only viable substrate and needs separate scoping.
- **Reddit retrieval is awaiting Data API approval** — the fetcher is written but stays out of the enabled list; RSS + HackerNews carry retrieval until then.
