from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # Database
    DATABASE_URL: str = ""

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    # Optional. Modern Supabase projects use asymmetric signing — we verify via JWKS at
    # {SUPABASE_URL}/auth/v1/.well-known/jwks.json with no shared secret needed.
    # Only fill SUPABASE_JWT_SECRET if your project is on legacy HS256 and you want a fallback.
    SUPABASE_JWT_SECRET: str = ""

    # Groq
    GROQ_API_KEY: str = ""
    # Primary (creative/voice) + fast (extraction) tiers. Migrated off the
    # deprecated llama-3.3-70b / llama-3.1-8b (Groq decommission 2026-08-16).
    # Primary = qwen3.6-27b: best founder-voice in A/B testing; the groq client
    # auto-pins reasoning_effort=none for it (qwen/ prefix). Fast = llama-4-scout:
    # clean JSON extraction, most generous free-tier limits, no reasoning params.
    GROQ_MODEL_PRIMARY: str = "qwen/qwen3.6-27b"
    GROQ_MODEL_FAST: str = "meta-llama/llama-4-scout-17b-16e-instruct"

    # LinkedIn (single app — personal posting in MVP)
    LINKEDIN_CLIENT_ID: str = ""
    LINKEDIN_CLIENT_SECRET: str = ""
    LINKEDIN_REDIRECT_URI: str = "http://127.0.0.1:8000/api/v1/auth/linkedin/callback"
    LINKEDIN_SCOPES: str = "openid,profile,email,w_member_social"
    LINKEDIN_API_VERSION: str = "202604"  # LinkedIn-Version header (YYYYMM)
    # Deferred — only populated if Community Management API is ever approved
    LINKEDIN_ORG_URN: str = ""

    # Mastodon (federated — OAuth client is registered dynamically per instance
    # at connect time, so no fixed client_id/secret here)
    MASTODON_REDIRECT_URI: str = "http://127.0.0.1:8000/api/v1/auth/mastodon/callback"
    MASTODON_CLIENT_NAME: str = "Nestwhirr AutoPost"
    MASTODON_SCOPES: str = "read write"

    # Threads (Meta-gated — single fixed app, 3-legged OAuth via Meta's OIDC).
    # client_id/secret are the Threads app's, NOT the parent Meta app's.
    # PLATFORM_THREADS_ENABLED stays false until Meta App Review clears
    # threads_basic + threads_content_publish (precedent: LinkedIn org posting).
    THREADS_APP_ID: str = ""
    THREADS_APP_SECRET: str = ""
    THREADS_REDIRECT_URI: str = "http://127.0.0.1:8000/api/v1/auth/threads/callback"
    THREADS_SCOPES: str = "threads_basic,threads_content_publish"
    THREADS_API_VERSION: str = "v1.0"
    PLATFORM_THREADS_ENABLED: bool = False

    # Instagram (Meta-gated — Instagram Login flow, NOT Facebook Login). The
    # lightweight path that skips the legacy Facebook-Page link; requires a
    # Creator/Business account. Scopes use the Instagram-Login naming
    # (instagram_business_*), the Facebook-Login variant is instagram_basic /
    # instagram_content_publish. PLATFORM_INSTAGRAM_ENABLED stays false until
    # Meta App Review clears (precedent: Threads / LinkedIn org posting).
    INSTAGRAM_APP_ID: str = ""
    INSTAGRAM_APP_SECRET: str = ""
    INSTAGRAM_REDIRECT_URI: str = "http://127.0.0.1:8000/api/v1/auth/instagram/callback"
    INSTAGRAM_SCOPES: str = "instagram_business_basic,instagram_business_content_publish"
    INSTAGRAM_API_VERSION: str = "v21.0"
    PLATFORM_INSTAGRAM_ENABLED: bool = False

    # X / Twitter (X API v2 — OAuth 2.0 Authorization Code + PKCE, single fixed
    # app). PAID API: no free tier for new developers as of 2026 (~$0.015/post).
    # Confidential client → token endpoint uses HTTP Basic auth (client_id:secret).
    # Access tokens are short-lived (~2h) with a rotating refresh token via the
    # `offline.access` scope, so the publisher refreshes proactively.
    # `media.write` is required for v2 media upload; `tweet.write` for posting.
    # PLATFORM_X_ENABLED stays false until the operator provisions a paid X app.
    X_CLIENT_ID: str = ""
    X_CLIENT_SECRET: str = ""
    X_REDIRECT_URI: str = "http://127.0.0.1:8000/api/v1/auth/x/callback"
    X_SCOPES: str = "tweet.read tweet.write users.read media.write offline.access"
    PLATFORM_X_ENABLED: bool = False

    # Reddit
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = "AutoPost/0.1"

    # App
    APP_SECRET_KEY: str = ""
    APP_BASE_URL: str = "http://127.0.0.1:8000"
    FRONTEND_BASE_URL: str = "http://localhost:3000"
    TIMEZONE: str = "UTC"
    LOG_LEVEL: str = "INFO"

    # Access control (Phase 14). Invite-only: the backend rejects any authenticated
    # email that isn't already provisioned in the `users` table, EXCEPT the bootstrap
    # admins below — the first-run super-admins who get the /admin panel and can then
    # invite everyone else. Comma-separated, case-insensitive. Keep this list tiny.
    # (The matching Supabase Auth user must exist before they can sign in — create it
    # via the Supabase dashboard, since public signups are disabled. See INSTRUCTIONS.md.)
    BOOTSTRAP_ADMIN_EMAILS: str = "nestwhirr@gmail.com"

    # Scheduler
    RETRIEVAL_CRON: str = "0 */6 * * *"
    ANALYTICS_CRON: str = "0 * * * *"
    TRENDS_CLEANUP_CRON: str = "30 3 * * *"
    TRENDS_CONSUMED_RETENTION_DAYS: int = 60

    # Rendering / brand
    BRAND_NAME: str = "Nestwhirr"

    # Supabase Storage (bucket holds rendered post visuals; public bucket so
    # LinkedIn's servers can fetch the URL at publish time)
    SUPABASE_STORAGE_BUCKET: str = "autopost-assets"

    # AI image generation (Phase 10). Primary: Cloudflare Workers AI flux-1-schnell
    # (free 10k neurons/day ≈ 260 images/day). Fallback: Pollinations (no auth).
    CLOUDFLARE_ACCOUNT_ID: str = ""
    CLOUDFLARE_AI_TOKEN: str = ""
    AI_IMAGE_MODEL: str = "@cf/black-forest-labs/flux-1-schnell"
    AI_IMAGE_STEPS: int = 4  # flux-schnell is a 4-step model
    AI_IMAGE_WIDTH: int = 800
    AI_IMAGE_HEIGHT: int = 800
    AI_IMAGE_TIMEOUT_SECONDS: float = 30.0
    # When True, append the brand style suffix (dark/editorial, muted palette)
    # to every AI-image prompt so generations composite cleanly into the
    # brand-wrap. When False (default), Flux is free to choose the palette and
    # lighting that best fit the subject — no forced black framing.
    AI_IMAGE_BRAND_STYLE: bool = False

    @property
    def linkedin_scope_list(self) -> list[str]:
        return [s.strip() for s in self.LINKEDIN_SCOPES.split(",") if s.strip()]

    @property
    def bootstrap_admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.BOOTSTRAP_ADMIN_EMAILS.split(",") if e.strip()}


settings = Settings()
