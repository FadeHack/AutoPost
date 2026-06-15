import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.user import User


class MastodonAccount(Base, TimestampMixin):
    """Connected Mastodon account for a dashboard user.

    Auth path is full OAuth 2.0, but Mastodon is federated — there's no central
    app registry, so the OAuth client is registered dynamically per instance
    (`POST /api/v1/apps`) at connect time. We store the resolved access token
    Fernet-encrypted; the client_id/client_secret are carried through the
    encrypted OAuth `state` and discarded after the callback (no separate
    `mastodon_apps` table).

    Mastodon access tokens don't expire by default and the standard flow issues
    no refresh token, so there are no `expires_at`/`refresh_token` columns — the
    orchestrator's auth-refresh branch guards on `hasattr(account,
    "refresh_token")` so the absence degrades cleanly.
    """

    __tablename__ = "mastodon_accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "instance_url",
            "handle",
            name="uq_mastodon_accounts_user_instance_handle",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Normalized instance origin, e.g. `https://mastodon.social`. Used as the
    # base URL for every API call to this account's home server.
    instance_url: Mapped[str] = mapped_column(String(255), nullable=False)
    # Username (local part), e.g. `nestwhirr`. Combined with the instance host
    # this is the fediverse handle `nestwhirr@mastodon.social`.
    handle: Mapped[str] = mapped_column(String(255), nullable=False)
    # Instance-local numeric account id from `verify_credentials`. Stable per
    # instance; kept for future reads (mentions, profile links).
    account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # OAuth access token — Fernet-encrypted.
    access_token: Mapped[str] = mapped_column(String, nullable=False)
    # Display name cached at connect time.
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship(back_populates="mastodon_accounts")
