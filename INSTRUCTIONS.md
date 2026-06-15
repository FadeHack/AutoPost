# INSTRUCTIONS.md — Operational Runbook

The "how" of this project. Read this when you need to *run* something — setup, dev, debug, deploy. Architectural "why" lives in `CONTEXT.md`; rules live in `CLAUDE.md`.

---

## Prerequisites

- **Python 3.12** (project uses 3.12.x; see `backend/.python-version`)
- **Node.js 20+** (`node --version`)
- **npm 10+** (`npm --version`)
- **Supabase project** (free tier is enough) — sign up at supabase.com
- **LinkedIn developer app (single, App #1)** with these products enabled:
  - "Share on LinkedIn"
  - "Sign In with LinkedIn using OpenID Connect"
  - *Note:* "Community Management API" (company-page posting) is deferred — it requires a registered legal entity. MVP posts as the authenticated member.
- **Reddit app** (script type) at https://www.reddit.com/prefs/apps
- **Groq API key** from https://console.groq.com

---

## First-Time Setup

```bash
# 1. From the repo root
cd /Users/sacomtechnologies/Desktop/projects/AutoPost

# 2. Backend
cd backend
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 3. Frontend
cd ../frontend
npm install

# 4. Environment — two files, not one
cp backend/.env.example backend/.env          # fill with backend secrets
cp frontend/.env.local.example frontend/.env.local   # fill with NEXT_PUBLIC_* only

# 5. Database migrations
cd backend
source venv/bin/activate
alembic upgrade head
```

### Generating APP_SECRET_KEY

One-time only (rotating it makes all stored LinkedIn tokens unreadable):

```bash
cd backend && source venv/bin/activate
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Paste the output into `backend/.env` as `APP_SECRET_KEY=...`.

### Supabase: create the Storage bucket (one-time)

Rendered post visuals live in a public Supabase Storage bucket so Phase 6's
LinkedIn publisher can fetch them via URL. One-time setup:

1. Supabase dashboard → your project → **Storage** → **New bucket**
2. **Name:** `autopost-assets` (must match `SUPABASE_STORAGE_BUCKET` in `backend/.env`)
3. **Public bucket:** ✅ on
4. **Allowed MIME types:** `image/png` (optional, tightens the bucket)
5. **File size limit:** `5 MB` (optional, sensible cap)

No new credential is needed — backend writes use the existing
`SUPABASE_SERVICE_ROLE_KEY`, which bypasses storage RLS.

### Supabase: which connection URL?

Supabase exposes three connection strings. **Use the Session Pooler URL on port 5432** for `DATABASE_URL`:

- Settings → Database → "Connection string" → "Session Pooler"
- Format: `postgresql+psycopg://postgres.PROJECTREF:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres`

Do **not** use the Transaction Pooler (port 6543) — it breaks Alembic's advisory locks. The Direct connection (also port 5432) works too but is IPv6-only by default; Session Pooler is the safe IPv4-friendly choice.

---

## Running Locally

Two terminals.

**Terminal 1 — Backend (FastAPI + APScheduler):**
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Health check: http://127.0.0.1:8000/health → `{"status":"ok"}`
API docs: http://127.0.0.1:8000/docs
On startup the logs should show: `APScheduler started`.

**Terminal 2 — Frontend (Next.js):**
```bash
cd frontend
npm run dev
```
Dashboard: http://localhost:3000

---

## Connecting LinkedIn (one-time)

1. Sign into the dashboard via Supabase magic link.
2. Click **"Connect LinkedIn"** in the header.
3. Approve the requested scopes: `openid`, `profile`, `email`, `w_member_social`.
4. You should be redirected back with a success banner showing your connected member name.
5. Verify in the DB:
   ```sql
   SELECT user_id, account_kind, member_sub, expires_at FROM linkedin_accounts;
   ```
   `account_kind` will be `'personal'` (MVP). The `access_token` / `refresh_token` columns are Fernet-encrypted blobs — don't expect plaintext.

---

## Common Operations

(These will work as the relevant phase lands. Currently Phase 0 — only health-check works.)

### Generate a draft
```bash
curl -X POST http://127.0.0.1:8000/api/v1/posts/generate \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"category":"founder_insight"}'
```
Or use the **"Generate draft"** button in the dashboard.

### Render an image for a post
```bash
# Auto-pick template by post category
curl -X POST http://127.0.0.1:8000/api/v1/posts/$POST_ID/render \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{}'

# Explicit template
curl -X POST http://127.0.0.1:8000/api/v1/posts/$POST_ID/render \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"template_id":"<uuid>"}'
```
Response includes `image_url` — a browser-fetchable path served by the dev-only
`StaticFiles` mount at `/static/assets`. PNG also lands on disk at
`backend/storage/assets/{post_id}/{asset_id}.png`. Every call creates a new
asset; old ones are kept.

### List rendered assets for a post
```bash
curl http://127.0.0.1:8000/api/v1/posts/$POST_ID/assets \
  -H "Authorization: Bearer $JWT"
```

### List available visual templates
```bash
curl http://127.0.0.1:8000/api/v1/templates -H "Authorization: Bearer $JWT"
```

### Schedule a post
Dashboard → draft detail → **Approve** → **Schedule** → pick date/time → confirm.
Verify the APScheduler job:
```sql
SELECT id, next_run_time FROM apscheduler_jobs;
```

### Force-publish now (bypass scheduler)
Dashboard → **Publish now**, or:
```bash
curl -X POST http://127.0.0.1:8000/api/v1/posts/$POST_ID/publish-now \
  -H "Authorization: Bearer $JWT"
```

### Manually refresh trends
```bash
curl -X POST http://127.0.0.1:8000/api/v1/trends/refresh \
  -H "Authorization: Bearer $JWT"
```

### Reset a failed post (move back to draft)
```sql
UPDATE posts
SET status='draft', error=NULL, scheduled_at=NULL
WHERE id='<post-id>';
DELETE FROM apscheduler_jobs WHERE id='publish_<post-id>';
```

---

## Debugging Recipes

### Where logs land
- Backend logs → stdout of the uvicorn process. Structured JSON in production, human-readable in dev.
- APScheduler logs are nested under the `apscheduler` logger.
- LLM call audit trail → `ai_generations` table.
- Publish attempts → `publishing_logs` table.

### Inspect scheduled APScheduler jobs
```sql
SELECT id, next_run_time
FROM apscheduler_jobs
ORDER BY next_run_time;
```

### Decode a LinkedIn API error
LinkedIn responses are saved to `publishing_logs.linkedin_response`. Useful keys:
- `serviceErrorCode` — LinkedIn-specific error code
- `message` — human-readable reason
- `status` — HTTP status

Common codes:
- `401` — token expired; refresh flow should have caught this, investigate `oauth.py`
- `403` — missing scope or LinkedIn org permission
- `422` — payload shape error; check `ugcPosts` body

### Re-render a stuck asset
```bash
curl -X POST http://127.0.0.1:8000/api/v1/posts/$POST_ID/render \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" -d '{}'
```
A new file lands in `backend/storage/assets/{post_id}/{asset_id}.png` and a new
`GeneratedAsset` row is inserted. Old assets are kept — disambiguate via
`created_at` on `GET /posts/{id}/assets`.

### Playwright fails to launch
```bash
cd backend
source venv/bin/activate
playwright install chromium
playwright install-deps   # Linux only
```

---

## Adding Things

### Add a new RSS feed source
1. Open `backend/app/retrieval/rss.py`.
2. Append the feed URL to the `DEFAULT_FEEDS` list.
3. No DB migration needed. Per-feed cap (`MAX_ENTRIES_PER_FEED`) and age cutoff (`MAX_ENTRY_AGE`) apply to every feed uniformly.
4. Trigger `POST /api/v1/trends/refresh` to verify it's pulled (check `per_source.rss` in the response increments by up to `MAX_ENTRIES_PER_FEED`).

### Add a new prompt template
1. Insert a new row in the `prompts` table with a unique `name`, the prompt `body`, and `is_active=true`.
2. Bump the `version` if you're replacing an existing one (set the old version `is_active=false`).
3. Code path that consumes prompts loads by `name` and the active version.

### Add a new visual template
1. Drop a new HTML file in `backend/app/rendering/templates/`. Keep the
   minimal-dark identity: black background, off-white serif headline, sans
   body, accent line + brand strap footer. Tailwind via CDN inside the file.
2. Write a one-row Alembic migration mirroring
   `d8e2f4a91c56_seed_templates.py` — bulk-insert `{name, category, html_path}`
   into `templates`. Run `alembic upgrade head`.
3. The new template is available via `template_id` on
   `POST /posts/{id}/render`. To make it a category default, edit
   `_DEFAULT_TEMPLATE_BY_CATEGORY` in `backend/app/rendering/renderer.py`.
4. It appears automatically in `GET /api/v1/templates` (the future picker
   feeds from this).

### Add a new content category
1. Add the category constant in `backend/app/schemas/post.py` (the `PostCategory` enum).
2. Add a prompt template for it (`prompts` table).
3. Optionally add a default visual template (`templates` table).
4. The dashboard category dropdown updates automatically from the API.

---

## Deployment

Not yet — MVP is local-only. This section will be expanded when Phase 8 hardening lands and the user requests deployment.

Sketch of expected steps when we get there:
- Backend → Render or Fly.io free tier (Dockerfile required).
- Frontend → Vercel (zero-config).
- DB → Supabase (already managed).
- APScheduler: keep in-process for now; if the API auto-scales, move to a single-instance worker process to avoid duplicate jobs.
- Env diffs: `APP_BASE_URL`, `FRONTEND_BASE_URL`, `LINKEDIN_REDIRECT_URI` all change to production hostnames; LinkedIn app must be updated with the new redirect URI.

---

## Quick Reference

| What | Where |
|---|---|
| Architecture & decisions | `CONTEXT.md` |
| Rules for Claude | `CLAUDE.md` |
| Progress / status | `CHECKLIST.md` |
| This file (how-to) | `INSTRUCTIONS.md` |
| Backend code | `backend/app/` |
| Frontend code | `frontend/app/` |
| DB migrations | `backend/alembic/versions/` |
| Generated images (dev) | `backend/storage/assets/` |
