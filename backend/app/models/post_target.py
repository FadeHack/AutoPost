import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Platform, TargetStatus, TimestampMixin, uuid_pk


class PostTarget(Base, TimestampMixin):
    """Per-platform fan-out for a Post.

    Picked at approve time (multi-select). Each row carries its own delivery
    lifecycle and external URN. The scheduler fires one job per target —
    different platforms have different rate limits and failure modes, so they
    must be independent.

    One platform per post — re-publishing to the same platform = a retry on
    the existing row, never a second one.
    """

    __tablename__ = "post_targets"
    __table_args__ = (
        UniqueConstraint("post_id", "platform", name="uq_post_targets_post_platform"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[Platform] = mapped_column(
        SAEnum(Platform, name="platform"),
        nullable=False,
        index=True,
    )
    status: Mapped[TargetStatus] = mapped_column(
        SAEnum(TargetStatus, name="target_status"),
        nullable=False,
        default=TargetStatus.pending,
        index=True,
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Platform-native post identifier after successful publish.
    # LinkedIn: `urn:li:share:XXX`. Bluesky: `at://did/app.bsky.feed.post/<tid>`.
    external_urn: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Last error if status='failed'.
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    # Raw request payload for replay / debugging.
    raw_request: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Platform-specific commentary written by the generator at draft-time so a
    # 300-char Bluesky post and a 1600-char LinkedIn post can coexist on the
    # same draft. NULL = orchestrator falls back to building from Post hook /
    # body / tags (the LinkedIn-canonical path).
    commentary: Mapped[str | None] = mapped_column(String, nullable=True)

    post = relationship("Post", back_populates="targets")
