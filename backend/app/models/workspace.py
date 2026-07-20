import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class Workspace(Base, TimestampMixin):
    """A tenant boundary (Phase 14). All workspace-private data — posts and their
    downstream rows, plus connected social accounts — is scoped by `workspace_id`.
    Shared data (trends, prompts, templates) is NOT scoped.

    One user per workspace today; the seam supports multiple members later (a
    membership table) without re-migrating the scoped data tables.
    """

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
