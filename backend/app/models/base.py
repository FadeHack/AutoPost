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


class Platform(str, enum.Enum):
    """Publishing destinations. MVP wires `linkedin` + `bluesky`; the rest
    are scaffolded for Phase 11 Chunks B–D."""
    linkedin = "linkedin"
    bluesky = "bluesky"
    mastodon = "mastodon"
    threads = "threads"
    instagram = "instagram"


class TargetStatus(str, enum.Enum):
    """Per-target delivery lifecycle. `posts.status` caps at `scheduled`;
    each `post_targets` row carries its own status from here on."""
    pending = "pending"
    publishing = "publishing"
    published = "published"
    failed = "failed"
