# AutoPost

AI-powered LinkedIn content automation, internal-first.

Pulls fresh tech / startup / AI trends from RSS + HackerNews, generates founder-voice drafts with Groq, renders branded visuals from HTML / Tailwind templates via headless Chromium, and publishes to a LinkedIn personal page on schedule — with human-in-the-loop approval at every step.

---

## What works today

End-to-end pipeline shipped through **Phase 6** (publishing). Hardening in **Phase 8**:

| Phase | Subsystem | Status |
|------|-----------|--------|
| 1 | Schema + Supabase Auth + LinkedIn OAuth | done |
| 2 | Retrieval (7 RSS feeds + HackerNews + APScheduler cron) | done |
| 3 | Intelligence (4-stage Groq pipeline + voice filter + DB-versioned prompts) | done |
| 4 | Rendering (4 Tailwind templates + Playwright + Supabase Storage CDN) | done |
| 5 | Dashboard (drafts queue, edit, approve, schedule, queue pages) | done |
| 6 | Publishing (LinkedIn `/rest/posts` + image upload + APScheduler one-shots) | done |
| 7 | Analytics | **deferred** — LinkedIn `r_member_social` is closed in 2026 |
| 8 | Hardening (token-expiry banner, failure surfacing + retry, restart smoke) | in progress |

See [`CHECKLIST.md`](./CHECKLIST.md) for the full milestone log and [`CONTEXT.md`](./CONTEXT.md) for the architecture + decisions.

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
│       ├── publishing/     OAuth, LinkedIn API client, publisher orchestration
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
Auth: Supabase Auth on the dashboard; LinkedIn 3-legged OAuth for posting.
Visuals: HTML + Tailwind → PNG via Playwright headless Chromium.
Scheduler: APScheduler in-process, `SQLAlchemyJobStore` for restart survival.

Locked = do not swap without explicit approval. See `CLAUDE.md`.

---

## Operational Reality Check

- **LinkedIn access tokens last ~60 days.** Standard dev apps don't get refresh tokens — refresh is only granted by the Marketing Developer Platform (legal-entity + manual review). The dashboard surfaces an amber banner at ≤10 days, red at ≤3 days, with a "Reconnect LinkedIn" CTA. Plan on re-OAuthing once every two months.
- **Company-Page posting is built but blocked** by LinkedIn-side Community Management API approval (same gate). The `account_kind` column + organization branch are wired today; activation = approval, not code.
- **Analytics (Phase 7) is deferred** — `r_member_social` is a closed permission in 2026. Member Data Portability is the only viable substrate and needs separate scoping.
