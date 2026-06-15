import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UserRole

if TYPE_CHECKING:
    from app.models.bluesky_account import BlueskyAccount
    from app.models.linkedin_account import LinkedInAccount
    from app.models.mastodon_account import MastodonAccount


class User(Base, TimestampMixin):
    """Dashboard user. `id` mirrors the Supabase Auth user UUID (no server-side default)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.admin,
    )

    linkedin_accounts: Mapped[list["LinkedInAccount"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    bluesky_accounts: Mapped[list["BlueskyAccount"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    mastodon_accounts: Mapped[list["MastodonAccount"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
