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
4. **Allowed MIME types:** leave blank, or `image/png, image/jpeg, image/webp, image/gif` (optional). Templated cards upload as PNG; AI images upload as **JPEG** (photographic — PNG blows past the size cap); **custom uploads** can be PNG/JPEG/WebP/GIF (posted raw, exactly as uploaded). If you restrict this list, any format you leave out will fail with a 400 on upload. If you restrict it to `image/png` only, AI-image and custom uploads both break.
5. **File size limit:** `5 MB` (optional). AI images render as JPEG q85 (~0.3–1 MB), well under this; templated PNGs are ~1–2 MB.

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

## Connecting Bluesky (one-time)

Bluesky uses an **App Password** rather than OAuth — the atproto Python SDK is pre-1.0 and still session-based.

1. On Bluesky web → **Settings → Privacy and security → App passwords** → "Add app password". Label it "Nestwhirr". Copy the generated `xxxx-xxxx-xxxx-xxxx` string immediately (Bluesky only shows it once).
2. On the dashboard → **Bluesky** section → **Connect Bluesky** → enter handle (e.g. `nestwhirr.bsky.social`) + the app password.
3. The backend calls `Client.login(...)` against the AT Protocol to validate before persisting. Success returns the connected DID. Both handle + password are stored in `bluesky_accounts`, the password Fernet-encrypted.
4. Verify in the DB:
   ```sql
   SELECT user_id, handle, did, display_name FROM bluesky_accounts;
   ```

Rotate the app password by revoking on bsky.app and reconnecting — the connect endpoint upserts on `(user_id, handle)`.

---

## Connecting Mastodon (one-time)

Mastodon is **federated** — every instance is its own server, so there's no central app to pre-register. The backend registers an OAuth client on your instance on the fly at connect time. Nothing to set up beforehand beyond the env vars below.

Env (already defaulted in `backend/.env.example`):
- `MASTODON_REDIRECT_URI=http://127.0.0.1:8000/api/v1/auth/mastodon/callback`
- `MASTODON_CLIENT_NAME=Nestwhirr AutoPost`
- `MASTODON_SCOPES=read write`

Steps:
1. On the dashboard → **Mastodon** section → **Connect Mastodon** → enter your instance (e.g. `mastodon.social` or `hachyderm.io`).
2. Backend calls `POST {instance}/api/v1/apps` to register a client, then redirects you to that instance's `/oauth/authorize`. Approve there.
3. On callback the backend exchanges the code, calls `verify_credentials`, and persists the Fernet-encrypted access token in `mastodon_accounts`. You're bounced back with a success banner.
4. Verify in the DB:
   ```sql
   SELECT user_id, instance_url, handle, display_name FROM mastodon_accounts;
   ```

Notes:
- Mastodon access tokens **don't expire** by default and no refresh token is issued, so there's no day-60 reconnect cycle like LinkedIn. If a token is revoked instance-side, reconnect.
- The per-instance `client_id`/`client_secret` are not stored — they ride inside the encrypted OAuth `state` and are discarded after callback.
- **Char limit reality:** Mastodon caps posts at 500 chars, but the canonical draft body is LinkedIn-shaped (~1100–1600 chars). Until Phase 12's per-platform prompt matrix lands, a Mastodon target on a normal draft will **fail the orchestrator's 500-char gate** with a clear error (this is expected). A hand-shortened ≤500-char draft publishes fine.

---

## Connecting Threads (Meta-gated)

Threads is a **single fixed Meta app** (LinkedIn-shaped OAuth, not federated). It's **disabled by default** behind `PLATFORM_THREADS_ENABLED` — you can't connect until Meta App Review approves `threads_basic` + `threads_content_publish` (same legal-gate shape as LinkedIn org posting). Code ships ahead of approval; pre-approval the API only works against the app's developer/tester accounts.

Env (in `backend/.env`, stubbed in `backend/.env.example`):
- `THREADS_APP_ID=` / `THREADS_APP_SECRET=` — the **Threads app's** client id/secret (Meta dashboard → Threads product → API setup), not the parent Meta app's.
- `THREADS_REDIRECT_URI=http://127.0.0.1:8000/api/v1/auth/threads/callback` (must match the Meta app config exactly).
- `THREADS_SCOPES=threads_basic,threads_content_publish`
- `THREADS_API_VERSION=v1.0`
- `PLATFORM_THREADS_ENABLED=false` → flip to `true` once approved. When false: `/auth/threads/start` returns 503 and the dashboard + `/generate` picker hide Threads.

Steps (once enabled + approved):
1. Dashboard → **Threads** section → **Connect Threads** → redirect to Meta's authorize → approve.
2. On callback the backend exchanges the code for a short-lived token, **immediately upgrades it to a 60-day long-lived token**, resolves `/me`, and persists the Fernet-encrypted token + `expires_at` in `threads_accounts`.
3. Verify:
   ```sql
   SELECT user_id, username, display_name, expires_at FROM threads_accounts;
   ```

Notes:
- **Token refresh is automatic + in place.** The 60-day long-lived token refreshes inside the publisher (`_ensure_fresh_token`, 2-day lead) — Threads' `/refresh_access_token` returns a fresh token, there's no separate refresh token. If the token fully dies (>60d untouched), a 401 surfaces and you reconnect.
- **Char limit:** Threads caps at 500 chars — same Phase-12 caveat as Mastodon. A LinkedIn-shaped draft fails the orchestrator's gate; a ≤500-char draft publishes.
- **Images:** Threads fetches the image from our public Supabase bucket URL itself — nothing to upload. Carousels publish as 2–20 image containers assembled into one CAROUSEL post.

---

## Connecting Instagram (Meta-gated)

Instagram uses Meta's **Instagram Login** flow (NOT Facebook Login — the lightweight path that skips the legacy Facebook-Page link). Like Threads it's a single fixed Meta app and is **disabled by default** behind `PLATFORM_INSTAGRAM_ENABLED` — you can't connect until Meta App Review approves the Instagram content-publish scopes. Code ships ahead of approval; pre-approval the API only works against the app's developer/tester accounts.

**Account prerequisite:** the Instagram account must be a **Creator or Business (Professional)** account — personal accounts can't publish via API. Converting is free, reversible, and takes ~30s in the IG mobile app settings.

Env (in `backend/.env`, stubbed in `backend/.env.example`):
- `INSTAGRAM_APP_ID=` / `INSTAGRAM_APP_SECRET=` — the **Instagram app's** client id/secret (Meta dashboard → Instagram product → API setup with Instagram Login).
- `INSTAGRAM_REDIRECT_URI=http://127.0.0.1:8000/api/v1/auth/instagram/callback` (must match the Meta app config exactly).
- `INSTAGRAM_SCOPES=instagram_business_basic,instagram_business_content_publish` (the Instagram-Login scope naming; the Facebook-Login variant is `instagram_basic`/`instagram_content_publish`).
- `INSTAGRAM_API_VERSION=v21.0`
- `PLATFORM_INSTAGRAM_ENABLED=false` → flip to `true` once approved. When false: `/auth/instagram/start` returns 503 and the dashboard + `/generate` picker hide Instagram.

Steps (once enabled + approved):
1. Convert the IG account to Creator/Business if it isn't already.
2. Dashboard → **Instagram** section → **Connect Instagram** → redirect to Meta's authorize → approve.
3. On callback the backend exchanges the code for a short-lived token (+ the IG-scoped `user_id`), **immediately upgrades it to a 60-day long-lived token**, resolves `/me`, and persists the Fernet-encrypted token + `expires_at` in `instagram_accounts`.
4. Verify:
   ```sql
   SELECT user_id, username, account_type, expires_at FROM instagram_accounts;
   ```

Notes:
- **Token refresh is automatic + in place** — same as Threads (`_ensure_fresh_token`, 2-day lead, `ig_refresh_token`, no separate refresh token; full death after ~60d untouched → reconnect).
- **Instagram requires an image.** There is no text-only IG post — a draft targeting Instagram with no rendered card fails the publish loudly. **Render a card first.** Use square (1080×1080) or 4:5 art; the minimal-dark templates already render square.
- **Caption limit:** 2200 chars (far above our LinkedIn-shaped body, so the char-limit gate effectively never trips for IG).
- **Images:** IG fetches the image from our public Supabase bucket URL itself — nothing to upload. Carousels publish as 2–10 image containers assembled into one CAROUSEL post.

---

## Connecting X / Twitter (paid API)

X is a **single fixed app**, OAuth 2.0 **Authorization Code + PKCE**. It's **disabled by default** behind `PLATFORM_X_ENABLED`. Unlike the Meta platforms, the gate here is **cost, not App Review**: the X API has **no free tier for new developers (as of 2026)** — posting is billed **~$0.015 per post** (~$0.20 if the post contains a link). You must provision a paid X app before you can connect.

**Setup:**
1. At [developer.x.com](https://developer.x.com), create a project + app, then enable **OAuth 2.0** with app type **Web App / Confidential client**.
2. Set the app's callback/redirect URL to match `X_REDIRECT_URI` (default `http://127.0.0.1:8000/api/v1/auth/x/callback`).
3. Ensure the app requests scopes `tweet.read tweet.write users.read media.write offline.access` (`media.write` is required to upload images; `offline.access` to get a refresh token).
4. Fill `backend/.env`:
   - `X_CLIENT_ID=` / `X_CLIENT_SECRET=` — the app's OAuth 2.0 Client ID/Secret.
   - `X_REDIRECT_URI=` — must exactly match the app's registered callback.
   - `X_SCOPES=tweet.read tweet.write users.read media.write offline.access`
   - `PLATFORM_X_ENABLED=false` → flip to `true` once the app is provisioned. When false: `/auth/x/start` returns 503 and the dashboard + `/generate` picker hide X.

**Connect:**
1. Dashboard → **Settings → Connections → X** section → **Connect X** → redirect to X's authorize → approve.
2. On callback the backend exchanges the code + PKCE verifier (carried in the encrypted state) for the access + refresh token pair, resolves `/2/users/me`, and persists both Fernet-encrypted tokens + `expires_at` in `x_accounts`.
3. Verify:
   ```sql
   SELECT username, x_user_id, expires_at FROM x_accounts;
   ```

Notes:
- **Token refresh is automatic — and actually exercised.** X access tokens are short-lived (~2h) with a **rotating** refresh token; `_ensure_fresh_token` (5-min lead) refreshes and re-persists BOTH tokens on every publish that lands near expiry. If the refresh token itself is revoked/dies, a 401 surfaces and you reconnect.
- **Char limit:** 280 (standard tier). Drafts targeting X get a Bluesky-shaped 280-char rewrite from the seeded per-platform prompt; an over-cap variant fails the orchestrator's gate (never truncated).
- **Images:** X does **not** fetch from a URL — the publisher downloads each rendered card from Supabase and uploads the bytes via `POST /2/media/upload` (one-shot, ≤4 images), then attaches the returned `media_id`s to the tweet.
- **Cost:** every publish to X bills your X account. Keep `PLATFORM_X_ENABLED=false` when you don't want to spend.

### Manual-post mode (generate-and-paste, no API cost)

You can keep `PLATFORM_X_ENABLED=true` **without connecting an X account** — use the pipeline to generate X-shaped content and post it by hand:

1. In `/drafts`, select **X** in the generate picker → each draft gets its own 280-char X rewrite.
2. Open the draft cockpit → platform preview → **X** tab → **Copy text** to grab the exact variant.
3. In the Visual panel, click **download** (next to "full size", and one per carousel slide) to save the rendered image, then attach it in the X composer by hand.
4. If you run **Publish now** / **Schedule** on a draft that includes X, the X leg is marked **"manual" (skipped)** — not failed — so your LinkedIn/Bluesky legs publish and the pipeline stays green. Connect a real X account later and X publishes via the API automatically.

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
Categories (Phase 12): `founder_insight`, `engineering_lesson`, `ai_automation`, `startup_opinion`, `dev_tooling`, `pricing_business_model`, `product_postmortem`, `design_thinking`. Pass `"platforms": ["linkedin","bluesky",...]` to fan out — each non-LinkedIn target is rewritten by that platform's prompt variant (LinkedIn-shaped body stays on the Post; per-platform text lands on `post_targets.commentary`).

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
1. Insert a new row in the `prompts` table with a `name` (= category), a `platform` (`linkedin`/`bluesky`/`mastodon`/`threads`/`instagram`, or NULL for the "any/legacy" variant), the prompt `body`, and `is_active=true`. The matrix key is `(name, platform, version)`.
2. Bump the `version` if you're replacing an existing one (set the old `(name, platform)` version `is_active=false`).
3. The generator loads via `_load_active_prompt(category, platform)` — it prefers the exact per-platform row, then falls back to `platform IS NULL`. The LinkedIn row is used by `run_pipeline` (Stage-1 writer); the other platforms' rows are used by `run_platform_rewrite` (Stage-2 rewrite of the canonical LinkedIn post). To re-voice a platform, flip `is_active` — no code deploy.

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
1. Add the value to the `PostCategory` enum in `backend/app/models/base.py`.
2. Alembic migration: add the value to the `post_category` PG enum **inside an `op.get_context().autocommit_block()`** (Postgres forbids using a freshly-added enum value in the same transaction), then `bulk_insert` its prompt rows. Mirror `c5f9a26b81e4_seed_phase12_categories.py` — ideally seed all **5 platform variants** (LinkedIn = Stage-1 writer prompt; Bluesky/Threads/Mastodon/Instagram = Stage-2 rewrite prompts honoring each char budget). At minimum seed the LinkedIn row.
3. Optionally map it in `_DEFAULT_TEMPLATE_BY_CATEGORY` (`renderer.py`); unmapped categories fall back to `insight_card`.
4. Frontend dropdown is a **manual TS list**, not API-driven: add the value to the `PostCategory` union + `CATEGORY_LABEL` + `CATEGORY_COLORS` in all four pages that render category chips (`app/drafts/page.tsx`, `app/drafts/[id]/page.tsx`, `app/scheduled/page.tsx`, `app/published/page.tsx`), and to `GENERATABLE` in `app/drafts/page.tsx` to expose it in the generate dropdown. `tsc --noEmit` will flag any map you miss.

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
