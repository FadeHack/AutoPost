import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PublishingStatus, TimestampMixin, uuid_pk


class PublishingLog(Base, TimestampMixin):
    """One row per LinkedIn publish attempt for a Post. Append-only."""

    __tablename__ = "publishing_logs"

    id: Mapped[uuid.UUID] = uuid_pk()
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[PublishingStatus] = mapped_column(
        SAEnum(PublishingStatus, name="publishing_status"),
        nullable=False,
    )
    linkedin_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
