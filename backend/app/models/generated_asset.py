import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, RenderKind, TimestampMixin, uuid_pk


class GeneratedAsset(Base, TimestampMixin):
    """A rendered visual (PNG) produced for a Post by a Template via Playwright."""

    __tablename__ = "generated_assets"

    id: Mapped[uuid.UUID] = uuid_pk()
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL only for operator-uploaded images (render_kind='upload'): a raw
    # passthrough has no HTML template. Every rendered row (template / ai_image)
    # still carries a valid template_id FK.
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="RESTRICT"),
        nullable=True,
    )
    # Path on disk (dev) or object-storage key (when deployed).
    image_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    # LinkedIn asset URN returned by /rest/images upload, used as the post's media reference.
    linkedin_asset_urn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 1-based slide index for carousel renders. NULL for single-image renders.
    # Carousel publishing orders assets by this; the row-level created_at is
    # not reliable (Postgres `now()` in a single transaction resolves once).
    slide_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 'template' = Playwright + HTML template (default). 'ai_image' = AI-generated
    # image (Flux via Cloudflare/Pollinations) composited into the brand-wrap
    # template. Both paths still produce one row + one PNG per render.
    render_kind: Mapped[RenderKind] = mapped_column(
        Enum(RenderKind, name="renderkind", native_enum=True),
        nullable=False,
        server_default=RenderKind.template.value,
    )
