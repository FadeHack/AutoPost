import uuid

from sqlalchemy import Boolean, Enum as SAEnum, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Platform, PostCategory, TimestampMixin, uuid_pk


class Prompt(Base, TimestampMixin):
    """Versioned prompt template loaded by the intelligence layer.

    Lookup pattern (Phase 12): get the row where
    (name, platform, is_active=true), preferring the per-platform variant and
    falling back to platform IS NULL ("any/legacy") when no variant exists.
    Bumping a prompt = insert new version with same (name, platform), set old
    version is_active=false.
    """

    __tablename__ = "prompts"
    __table_args__ = (
        # Phase 12: the matrix key is (name, platform, version). NULL platform
        # is the legacy/any variant. Postgres treats NULLs as distinct, so
        # multiple platform=NULL versions coexist by version, as before.
        UniqueConstraint(
            "name", "platform", "version", name="uq_prompts_name_platform_version"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    category: Mapped[PostCategory] = mapped_column(
        SAEnum(PostCategory, name="post_category"),
        nullable=False,
    )
    # Phase 12: per-platform prompt matrix. NULL = "any/legacy" variant used as
    # the graceful fallback when a category has no platform-specific prompt yet.
    platform: Mapped[Platform | None] = mapped_column(
        SAEnum(Platform, name="platform"),
        nullable=True,
    )
    body: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
