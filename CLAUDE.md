# CLAUDE.md — Rules & Guardrails for Claude

Auto-loaded by Claude on every session inside this repo. Imperative rules — what to do, what never to do — so silent drift from the project brief is impossible.

**Read order at the start of every session:**
1. `CLAUDE.md` (this file) — the rules
2. `CHECKLIST.md` — what's done, what's next
3. `CONTEXT.md` — current architecture
4. `INSTRUCTIONS.md` — only if you need to run something

---

## Non-Negotiable Philosophy

- Content the platform produces must read **founder-like, opinionated, human** — never generic AI spam. Every prompt change must respect this.
- The **retrieval layer is the only source of "what's new"** — the LLM must never be asked to "know the latest news." Retrieval fetches, intelligence analyzes.
- This is an internal-first automation system for one company page now, but every abstraction must support multi-company / multi-platform later without rewrites.

---

## Locked Tech Choices

Do not swap these without explicit user approval.

- **LLM**: Groq — `llama-3.3-70b-versatile` (primary), `llama-3.1-8b-instant` (fast).
- **Image generation**: HTML + TailwindCSS templates rendered to PNG via Playwright (headless Chromium). Diffusion image gen is *secondary only*, reserved for memes / illustrations / campaign art.
- **Backend**: FastAPI + SQLAlchemy + Alembic. Async by default.
- **Scheduler**: APScheduler, in-process, with `SQLAlchemyJobStore` backed by Postgres. Started in FastAPI lifespan hook.
- **Database**: Supabase (managed Postgres) on the free tier. **Always use the Session Pooler URL on port 5432** — for both Alembic migrations AND app queries. The Transaction Pooler (port 6543) breaks Alembic advisory locks; never use it.
- **Frontend**: Next.js (App Router) + TailwindCSS.
- **Auth**: Supabase Auth (email magic link) on the dashboard. Backend verifies Supabase JWTs via JWKS.
- **LinkedIn**: single dev app, 3-legged OAuth + refresh, posting as the authenticated **member** (`urn:li:person:...`). Tokens encrypted at rest with Fernet. Endpoint: `/rest/posts` with `LinkedIn-Version: YYYYMM` header (NOT the deprecated `/v2/ugcPosts`).
- **Local Python**: `venv` in `backend/venv/`, activated via `source backend/venv/bin/activate`.

## Environment Files

**Two files, never one.** This matches pydantic-settings + Next.js conventions and prevents backend secrets from leaking to the browser.

- `backend/.env` — all backend secrets (LinkedIn, Reddit, Groq, DB, Fernet, Supabase service_role)
- `frontend/.env.local` — only `NEXT_PUBLIC_*` values (safe to bundle into browser JS)
- **Do not** create a root-level `.env`. The backend reads its own file from `backend/`; Next.js reads its own from `frontend/`.

---

## Architectural Rules

- Subsystems live under `backend/app/{retrieval,intelligence,rendering,scheduler,publishing,analytics}` and **communicate via the database or in-process function calls — never HTTP between subsystems**.
- A new **retrieval source** → implement the `Fetcher` ABC in `backend/app/retrieval/base.py`. One file.
- A new **publishing target** → implement the `Publisher` ABC in `backend/app/publishing/`. MVP only implements `LinkedInPublisher`.
- **Prompts live in the `prompts` table** (versioned). Do not hardcode prompt strings in Python — load by name+version from the DB.
- **Visual templates** live as HTML files in `backend/app/rendering/templates/` + a row in the `templates` table. Adding a template = drop an HTML file + insert a row.
- Posts move through one **status lifecycle only**: `draft → approved → scheduled → publishing → (published | failed)`. Never skip states.
- LinkedIn tokens never leave the backend. The frontend never sees them.
- **`linkedin_accounts.account_kind`** is an enum `('personal', 'organization')`. MVP only uses `'personal'`. The `'organization'` branch is deferred (requires a registered legal entity + Community Management API approval) but the schema column exists today so the future cutover is zero-rework. **Do not delete this column or hardcode `'personal'`** — the publisher reads it at runtime.
- The publisher chooses the LinkedIn `author` URN as:
  - if `account_kind='organization'` → `urn:li:organization:<org_urn>`
  - else → `urn:li:person:<member_sub>`

---

## Forbidden in MVP

These are deferred — do not pull them forward without explicit user approval.

- Celery, Redis as a broker, microservices
- Vector DB / RAG, fine-tuned voice models
- Multi-platform posting code (Twitter, Threads, etc.) — abstractions support it, implementations do not
- Autonomous agents, AI comment replies, competitor analysis
- Team collaboration / multi-tenant logic beyond the existing `org_urn` column
- Diffusion image generation as the primary visual path

---

## Founder Voice — AI Tells to Strip

The output post-processor (`backend/app/intelligence/voice.py`) must remove these. Prompts must not produce them.

**Phrases banned outright:**
- "delve", "in conclusion", "moreover", "furthermore", "it's worth noting"
- "in today's fast-paced world", "navigating the complexities of"
- "I hope this helps", "feel free to"
- Excessive hedging: "it could be argued", "one might say"

**Punctuation / formatting tells:**
- Em-dash used as a separator (`—`) — use a period or line break instead
- Triple-bullet lists with no narrative
- Closing summary paragraph ("to summarize…")

**Structural rules for every post:**
- Hook in the **first line** — must work alone, before "see more" expands
- Short lines (≤ 12 words). Line breaks for breathing room
- No closing summary
- Hashtags: **max 3**, lowercase, at the end. No hashtag spam
- One opinion per post, not a survey

---

## Web Search — When to Use It

Training data drifts. Third-party APIs ship breaking changes, deprecate endpoints, rotate auth flows, and renumber versions on schedules I do not know about. **Do not guess from memory when the cost of being wrong is real code.**

**Always run a web search before:**
- Integrating or modifying anything that touches a third-party API or SDK (LinkedIn, Supabase, Groq, Reddit, Playwright, Next.js, FastAPI, SQLAlchemy, Alembic, APScheduler, etc.) — verify the current endpoint, header, scope, auth flow, version string, and any recent deprecations.
- Picking a model ID, API version pin, or library version — confirm the latest stable that matches our constraints.
- Debugging a third-party error message you have not seen verbatim in this repo before — pull the current docs / changelog / known-issue threads.
- The user mentions a vendor change, a new feature, or "the latest" anything.
- Pinning or upgrading a dependency in `requirements.txt` or `package.json`.

**Why:** every wrong-from-memory integration costs the user a real debugging cycle, and silent staleness compounds across phases. A 30-second search beats a 30-minute wrong path.

**How to apply:** prefer official docs and changelogs over blog posts. Cross-check at least two sources for non-trivial changes (e.g., LinkedIn version headers, OAuth scope renames). When the search result conflicts with what's already wired up in this repo, surface the conflict to the user before changing code.

---

## Mandatory Housekeeping

After every implementation step:
1. Update `CONTEXT.md` with architecture deltas + decisions made.
2. Update `CHECKLIST.md` — tick completed items, append any discovered work or blockers.
3. If a setup step, command, or runtime expectation changed, update `INSTRUCTIONS.md`.

These three docs must never lag the code. If you finished work and didn't update them, the work isn't finished.

---

## Security

- All secrets via `.env` (gitignored). `.env.example` carries empty keys for documentation.
- LinkedIn `access_token` / `refresh_token` stored Fernet-encrypted using `APP_SECRET_KEY`.
- Every FastAPI route (except OAuth callbacks) requires a valid Supabase JWT via a shared dependency.
- Backend binds to `127.0.0.1` during local dev.
- Never commit `.env`, `backend/storage/`, `frontend/.next/`, or any LinkedIn token.

---

## When in Doubt

- Check `CONTEXT.md` for what already exists before writing new code.
- Check `CHECKLIST.md` for what phase you're in and what's next.
- If a decision changes the architecture, record it in `CONTEXT.md` under "Decisions made" with date + rationale.
- If you're unsure whether something belongs in MVP, ask the user. The brief explicitly says: avoid overengineering.
