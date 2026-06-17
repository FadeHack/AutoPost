import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.user import User


class ThreadsAccount(Base, TimestampMixin):
    """Connected Threads account for a dashboard user.

    Auth path is Meta's 3-legged OAuth against a single fixed Threads app
    (unlike Mastodon's federated per-instance registration). The short-lived
    code is exchanged for a long-lived access token (60 days) which is
    Fernet-encrypted at rest.

    Threads refreshes the long-lived token **in place** — `GET /refresh_access_token`
    returns a fresh access token, not a separate refresh token — so there's an
    `expires_at` but no `refresh_token` column. The publisher's
    `_ensure_fresh_token` refreshes proactively on staleness. The orchestrator's
    forced-refresh-on-401 branch guards on `hasattr(account, "refresh_token")`,
    so its absence degrades cleanly: a hard 401 (e.g. token >60d dead) becomes
    terminal after retries and the operator reconnects.
    """

    __tablename__ = "threads_accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "threads_user_id",
            name="uq_threads_accounts_user_threads_user",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Threads-scoped numeric user id from the token exchange. Used as the path
    # segment in `graph.threads.net/v1.0/{threads_user_id}/threads`.
    threads_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Public @username resolved at connect time; displayed on the dashboard.
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    # Long-lived OAuth access token — Fernet-encrypted.
    access_token: Mapped[str] = mapped_column(String, nullable=False)
    # Long-lived token expiry (~60 days). Drives the proactive refresh in the
    # publisher and the dashboard "token expiring" surface.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Display name cached at connect time.
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship(back_populates="threads_accounts")
