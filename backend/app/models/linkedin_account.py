import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AccountKind, Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.user import User


class LinkedInAccount(Base, TimestampMixin):
    """Connected LinkedIn account for a dashboard user.

    `account_kind='personal'` (MVP) → posts as `urn:li:person:<member_sub>`.
    `account_kind='organization'` (deferred) → posts as `urn:li:organization:<org_urn>`.
    The publisher chooses author URN at runtime based on this column.
    """

    __tablename__ = "linkedin_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "account_kind", name="uq_linkedin_accounts_user_kind"),
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
    account_kind: Mapped[AccountKind] = mapped_column(
        SAEnum(AccountKind, name="linkedin_account_kind"),
        nullable=False,
    )

    # OIDC `sub` claim for the LinkedIn member (the long-form personal URN suffix).
    # Null when account_kind='organization'.
    member_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Organization URN suffix. Null when account_kind='personal'.
    org_urn: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Token storage — Fernet-encrypted ciphertext (base64 ASCII), stored as TEXT.
    access_token: Mapped[str] = mapped_column(String, nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    # Display fields cached at connection time (name from OIDC profile, etc.).
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship(back_populates="linkedin_accounts")
