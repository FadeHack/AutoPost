import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

__all__ = [
    "Base",
    "TimestampMixin",
    "uuid_pk",
    "UserRole",
    "AccessRequestStatus",
    "AccountKind",
    "TrendSource",
    "PostCategory",
    "PostStatus",
    "TemplateCategory",
    "PublishingStatus",
    "RenderKind",
    "Platform",
    "TargetStatus",
]


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# --- Enum types (become Postgres ENUM types via SQLAlchemy Enum column) ---


class UserRole(str, enum.Enum):
    admin = "admin"
    editor = "editor"
    viewer = "viewer"


class AccessRequestStatus(str, enum.Enum):
    """Public access-request lifecycle (Phase 14). `pending` on intake; an admin
    moves it to `approved` (→ Supabase invite + provisioned user/workspace) or
    `denied`. Terminal states are `approved`/`denied`."""
    pending = "pending"
    approved = "approved"
    denied = "denied"


class AccountKind(str, enum.Enum):
    personal = "personal"
    organization = "organization"


class TrendSource(str, enum.Enum):
    rss = "rss"
    hackernews = "hackernews"
    reddit = "reddit"


class PostCategory(str, enum.Enum):
    founder_insight = "founder_insight"
    engineering_lesson = "engineering_lesson"
    ai_automation = "ai_automation"
    startup_opinion = "startup_opinion"
    technical_humor = "technical_humor"
    carousel = "carousel"
    # Phase 12 Chunk B — content surface expansion.
    dev_tooling = "dev_tooling"
    pricing_business_model = "pricing_business_model"
    product_postmortem = "product_postmortem"
    design_thinking = "design_thinking"


class PostStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"
    scheduled = "scheduled"
    publishing = "publishing"
    published = "published"
    failed = "failed"


class TemplateCategory(str, enum.Enum):
    quote = "quote"
    insight = "insight"
    metric = "metric"
    carousel = "carousel"
    ai_image = "ai_image"


class PublishingStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    success = "success"
    failure = "failure"


class RenderKind(str, enum.Enum):
    template = "template"
    ai_image = "ai_image"
    # Operator-uploaded custom image. Raw passthrough — no Playwright render,
    # no template (template_id is NULL for these rows), posted exactly as
    # uploaded. See app/api/posts.py :: upload_image.
    upload = "upload"


class Platform(str, enum.Enum):
    """Publishing destinations. MVP wires `linkedin` + `bluesky`; the rest
    are scaffolded for Phase 11 Chunks B–D. `x` (Twitter) added Phase 11
    Chunk F — full X API v2 OAuth2-PKCE publisher (paid API, no free tier)."""
    linkedin = "linkedin"
    bluesky = "bluesky"
    mastodon = "mastodon"
    threads = "threads"
    instagram = "instagram"
    x = "x"


class TargetStatus(str, enum.Enum):
    """Per-target delivery lifecycle. `posts.status` caps at `scheduled`;
    each `post_targets` row carries its own status from here on.

    `skipped` = the platform is enabled for content generation but has no API
    account connected, so the fan-out intentionally did NOT publish it (the
    operator posts it by hand — e.g. X while not connected). It's terminal and
    is NOT a failure: aggregation ignores skipped legs when rolling posts up."""
    pending = "pending"
    publishing = "publishing"
    published = "published"
    failed = "failed"
    skipped = "skipped"
