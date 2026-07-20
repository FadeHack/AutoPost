import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AccessRequestStatus, Base, TimestampMixin, uuid_pk


class AccessRequest(Base, TimestampMixin):
    """A logged-out visitor's request to join the platform (Phase 14, invite-only).

    Submitted from the public marketing landing (no auth). An admin reviews the
    queue in `/admin` and either approves (→ Supabase invite + provisioned
    user/workspace, role `editor`) or denies. Not a tenant-scoped table — these
    exist before any workspace does.
    """

    __tablename__ = "access_requests"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    status: Mapped[AccessRequestStatus] = mapped_column(
        SAEnum(AccessRequestStatus, name="access_request_status"),
        nullable=False,
        default=AccessRequestStatus.pending,
        index=True,
    )

    # Audit: who acted and when (set on approve/deny). `reviewed_by` → the admin
    # user's id; nullable + `ondelete=SET NULL` so deleting an admin never drops
    # the request history.
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
