import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PostCategory, PostStatus, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.post_target import PostTarget


class Post(Base, TimestampMixin):
    """A draft in the editorial lifecycle.

    `posts.status` caps at `scheduled` post-Phase 11. Per-platform delivery
    (publishing → published|failed) is tracked on `post_targets`, one row per
    selected platform. `posts.status` becomes `published` once all targets
    terminate with ≥1 success, `failed` if all fail.

    Status lifecycle: draft → approved → scheduled → (published | failed)
    where the terminal states are aggregated from `post_targets`.
    """

    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Tenant boundary (Phase 14). Every post belongs to exactly one workspace.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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

    # Per-platform delivery rows. Created at approve time when the operator
    # selects targets; one per `(post_id, platform)`. Drives the publisher.
    # `lazy='selectin'` so PostRead serialization (from_attributes=True) doesn't
    # trip the async lazy-load guard.
    targets: Mapped[list["PostTarget"]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="PostTarget.created_at",
    )
