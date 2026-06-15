import uuid

from sqlalchemy import Boolean, Enum as SAEnum, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PostCategory, TimestampMixin, uuid_pk


class Prompt(Base, TimestampMixin):
    """Versioned prompt template loaded by the intelligence layer.

    Lookup pattern: get the row where (name, is_active=true).
    Bumping a prompt = insert new version with same name, set old version is_active=false.
    """

    __tablename__ = "prompts"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_prompts_name_version"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    category: Mapped[PostCategory] = mapped_column(
        SAEnum(PostCategory, name="post_category"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
