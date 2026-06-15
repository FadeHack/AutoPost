import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as SAEnum, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, TrendSource, uuid_pk


class Trend(Base, TimestampMixin):
    """An ingested item from a retrieval source.

    Dedup is enforced by (source, source_id) — e.g. (rss, '<rss-entry-guid>'),
    (hackernews, '<HN item id>'), (reddit, '<reddit fullname like t3_abc>').
    """

    __tablename__ = "trends"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_trends_source_source_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source: Mapped[TrendSource] = mapped_column(
        SAEnum(TrendSource, name="trend_source"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
