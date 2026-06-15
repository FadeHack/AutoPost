import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as SAEnum, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PostCategory, PostStatus, TimestampMixin, uuid_pk


class Post(Base, TimestampMixin):
    """A LinkedIn post in the draft → published lifecycle.

    Status lifecycle (no skipping): draft → approved → scheduled → publishing → (published | failed).
    """

    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = uuid_pk()
    category: Mapped[PostCategory] = mapped_column(
        SAEnum(PostCategory, name="post_category"),
        nullable=False,
        index=True,
    )
    hook: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    # Trends that informed this draft (audit + future analytics).
    source_trend_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        default=list,
    )

    status: Mapped[PostStatus] = mapped_column(
        SAEnum(PostStatus, name="post_status"),
        nullable=False,
        default=PostStatus.draft,
        index=True,
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # LinkedIn post URN after successful publish (e.g. 'urn:li:share:XXX').
    linkedin_urn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Last error message if status='failed'.
    error: Mapped[str | None] = mapped_column(String, nullable=True)

    # Raw LinkedIn payload that was POSTed, for replay / debugging.
    raw_request: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Per-template content extracted by Stage 4 of the generator.
    # Shape: {pull_quote, metric_value, metric_label, carousel_slides[{text}]}.
    # Nullable — existing rows stay NULL until first re-render (lazy-fills).
    extracts: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
