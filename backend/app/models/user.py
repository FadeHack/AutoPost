import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UserRole

if TYPE_CHECKING:
    from app.models.bluesky_account import BlueskyAccount
    from app.models.instagram_account import InstagramAccount
    from app.models.linkedin_account import LinkedInAccount
    from app.models.mastodon_account import MastodonAccount
    from app.models.threads_account import ThreadsAccount
    from app.models.workspace import Workspace
    from app.models.x_account import XAccount


class User(Base, TimestampMixin):
    """Dashboard user. `id` mirrors the Supabase Auth user UUID (no server-side default)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)

    # The tenant this user belongs to (Phase 14). One user per workspace today.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Safe-by-default: new rows are `editor`, never `admin`. Admin is granted only to
    # bootstrap admins (config) or explicitly via the /admin panel (Phase 14).
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.editor,
    )

    workspace: Mapped["Workspace"] = relationship()

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
    threads_accounts: Mapped[list["ThreadsAccount"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    instagram_accounts: Mapped[list["InstagramAccount"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    x_accounts: Mapped[list["XAccount"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
