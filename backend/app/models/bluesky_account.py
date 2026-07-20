import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.user import User


class BlueskyAccount(Base, TimestampMixin):
    """Connected Bluesky account for a dashboard user.

    Auth path is App Password (not OAuth) — atproto Python SDK (pre-1.0) is
    still session-based. Both handle and app password live Fernet-encrypted.
    The publisher calls `client.login(handle, app_password)` on each publish;
    session caching is intentionally skipped (tokens are short-lived, app
    passwords are stable, and avoiding session persistence dodges a class of
    refresh bugs).
    """

    __tablename__ = "bluesky_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "handle", name="uq_bluesky_accounts_user_handle"),
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
    # Handle stored plaintext — public identifier (e.g. `nestwhirr.bsky.social`),
    # not a secret. Used to look the account up; also displayed in the dashboard.
    handle: Mapped[str] = mapped_column(String(255), nullable=False)
    # DID resolved at connect time. Stable across handle renames; used as the
    # `repo` parameter in atproto record-create calls.
    did: Mapped[str] = mapped_column(String(255), nullable=False)
    # App password — Fernet-encrypted. Bluesky issues an app-specific token
    # that survives the user's main-password rotation.
    app_password: Mapped[str] = mapped_column(String, nullable=False)
    # Display name cached at connect time.
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship(back_populates="bluesky_accounts")
