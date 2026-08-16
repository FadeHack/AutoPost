import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TrendConsumption(Base):
    """Per-workspace read-state over the shared `trends` pool (2026-08-16).

    Trends themselves stay shared/global (one RSS+HN fetch serves every
    workspace — see CLAUDE.md "Architectural Rules"); only *consumption*
    ("did my workspace act on this one") is workspace-scoped, so one
    workspace generating a draft from a trend doesn't silently mark it
    consumed for every other workspace. Composite PK — one row per
    (trend, workspace) pair, upserted on consume, deleted on un-consume.
    Both FKs cascade: deleting the trend (retention sweep) or the workspace
    cleans up its rows automatically.
    """

    __tablename__ = "trend_consumptions"

    trend_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trends.id", ondelete="CASCADE"),
        primary_key=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    consumed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
