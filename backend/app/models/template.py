import uuid

from sqlalchemy import Enum as SAEnum, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TemplateCategory, TimestampMixin, uuid_pk


class Template(Base, TimestampMixin):
    """Registered visual template for the rendering layer.

    `html_path` is relative to backend/app/rendering/templates/.
    Adding a new template = drop an HTML file in that dir + insert a row here.
    """

    __tablename__ = "templates"
    __table_args__ = (
        UniqueConstraint("name", name="uq_templates_name"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[TemplateCategory] = mapped_column(
        SAEnum(TemplateCategory, name="template_category"),
        nullable=False,
        index=True,
    )
    html_path: Mapped[str] = mapped_column(String(512), nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
