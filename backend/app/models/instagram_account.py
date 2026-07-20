import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.user import User


class InstagramAccount(Base, TimestampMixin):
    """Connected Instagram account for a dashboard user.

    Auth path is Meta's **Instagram Login** flow (NOT Facebook Login) — the
    lightweight 3-legged OAuth against a single fixed Instagram app that skips
    the legacy Facebook-Page link. Requires the connected account to be a
    Creator/Business (Professional) account; personal accounts can't publish
    via API. The short-lived code is exchanged for a long-lived access token
    (60 days) which is Fernet-encrypted at rest.

    Like Threads, Instagram refreshes the long-lived token **in place** —
    `GET /refresh_access_token?grant_type=ig_refresh_token` returns a fresh
    access token, not a separate refresh token — so there's an `expires_at` but
    no `refresh_token` column. The publisher's `_ensure_fresh_token` refreshes
    proactively on staleness; the orchestrator's forced-refresh-on-401 branch
    guards on `hasattr(account, "refresh_token")`, so its absence degrades
    cleanly (a hard 401 becomes terminal after retries; operator reconnects).
    """

    __tablename__ = "instagram_accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "instagram_user_id",
            name="uq_instagram_accounts_user_ig_user",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Tenant boundary (Phase 14). Scoping key for this connected account.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Instagram-scoped numeric user id from the token exchange. Used as the path
    # segment in `graph.instagram.com/{ver}/{instagram_user_id}/media`.
    instagram_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Public @username resolved at connect time; displayed on the dashboard.
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    # Long-lived OAuth access token — Fernet-encrypted.
    access_token: Mapped[str] = mapped_column(String, nullable=False)
    # Long-lived token expiry (~60 days). Drives the proactive refresh in the
    # publisher and the dashboard "token expiring" surface.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Account type (e.g. BUSINESS / MEDIA_CREATOR) cached at connect time.
    account_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped["User"] = relationship(back_populates="instagram_accounts")
