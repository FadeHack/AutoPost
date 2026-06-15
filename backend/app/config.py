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
    GROQ_MODEL_PRIMARY: str = "llama-3.3-70b-versatile"
    GROQ_MODEL_FAST: str = "llama-3.1-8b-instant"

    # LinkedIn (single app — personal posting in MVP)
    LINKEDIN_CLIENT_ID: str = ""
    LINKEDIN_CLIENT_SECRET: str = ""
    LINKEDIN_REDIRECT_URI: str = "http://127.0.0.1:8000/api/v1/auth/linkedin/callback"
    LINKEDIN_SCOPES: str = "openid,profile,email,w_member_social"
    LINKEDIN_API_VERSION: str = "202604"  # LinkedIn-Version header (YYYYMM)
    # Deferred — only populated if Community Management API is ever approved
    LINKEDIN_ORG_URN: str = ""

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

    @property
    def linkedin_scope_list(self) -> list[str]:
        return [s.strip() for s in self.LINKEDIN_SCOPES.split(",") if s.strip()]


settings = Settings()
