import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.user import User


class XAccount(Base, TimestampMixin):
    """Connected X (Twitter) account for a dashboard user.

    Auth path is X API v2 OAuth 2.0 Authorization Code + PKCE against a single
    fixed X app (like LinkedIn/Threads, unlike Mastodon's federated
    registration). UNLIKE every other platform here, X access tokens are
    short-lived (~2 hours) and X issues a **rotating** refresh token (via the
    `offline.access` scope) — each refresh returns a NEW access token AND a NEW
    refresh token. So both are Fernet-encrypted at rest and both are re-persisted
    on every refresh. The publisher's `_ensure_fresh_token` refreshes proactively
    on staleness (the 2h window means this path is actually exercised, unlike
    LinkedIn's structurally-dead refresh).

    NOTE: the X API is paid (no free tier for new developers as of 2026) —
    ~$0.015 per post created. `PLATFORM_X_ENABLED` gates the connect flow.
    """

    __tablename__ = "x_accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "x_user_id",
            name="uq_x_accounts_user_x_user",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Numeric X user id from GET /2/users/me. Stable identity for the account.
    x_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Public @username, resolved at connect time. Used to build the public
    # status URL (https://x.com/<username>/status/<tweet_id>).
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    # Short-lived OAuth2 access token (~2h) — Fernet-encrypted.
    access_token: Mapped[str] = mapped_column(String, nullable=False)
    # Rotating refresh token (offline.access) — Fernet-encrypted. Replaced on
    # every refresh. Nullable in case a token was issued without offline.access.
    refresh_token: Mapped[str | None] = mapped_column(String, nullable=True)
    # Access-token expiry (~2h out). Drives the proactive refresh in the
    # publisher.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Display name cached at connect time.
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship(back_populates="x_accounts")
