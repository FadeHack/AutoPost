"""post_targets + bluesky_accounts + publishing_logs.target_id (Phase 11 Chunk A)

Revision ID: c9e1f02db4a7
Revises: 3b27fdcf2346
Create Date: 2026-06-15 00:00:00.000000

Phase 11 Chunk A — ends LinkedIn-only assumption.

Schema changes:
  - New enum `platform` (linkedin, bluesky, mastodon, threads, instagram).
  - New enum `target_status` (pending, publishing, published, failed).
  - New table `post_targets` — one row per (post, platform) selected at approve time.
  - New table `bluesky_accounts` — App-Password auth, Fernet-encrypted creds.
  - `publishing_logs.target_id` nullable FK to post_targets.

Backfill:
  - Every existing `published` post gets one `post_targets` row
    (platform=linkedin, status=published, external_urn=posts.linkedin_urn,
    published_at=posts.published_at). Preserves the single-platform history.
  - `failed` posts → backfill row (platform=linkedin, status=failed,
    error=posts.error). Retry path still works.
  - `scheduled` posts → backfill row (platform=linkedin, status=pending,
    scheduled_at=posts.scheduled_at). Caller must reschedule via the new
    per-target scheduler.
  - `draft` / `approved` posts → no rows. Operator picks targets at next approve.

`posts.linkedin_urn` is kept (nullable) for one release for any pre-migration
reads; removed in a Phase 12 cleanup migration.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c9e1f02db4a7"
down_revision: Union[str, None] = "3b27fdcf2346"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    platform_enum = sa.Enum(
        "linkedin",
        "bluesky",
        "mastodon",
        "threads",
        "instagram",
        name="platform",
    )
    platform_enum.create(bind, checkfirst=True)

    target_status_enum = sa.Enum(
        "pending",
        "publishing",
        "published",
        "failed",
        name="target_status",
    )
    target_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "post_targets",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "post_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "platform",
            postgresql.ENUM(name="platform", create_type=False),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="target_status", create_type=False),
            nullable=False,
            server_default="pending",
            index=True,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_urn", sa.String(length=512), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column(
            "raw_request",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("post_id", "platform", name="uq_post_targets_post_platform"),
    )

    op.create_table(
        "bluesky_accounts",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("handle", sa.String(length=255), nullable=False),
        sa.Column("did", sa.String(length=255), nullable=False),
        sa.Column("app_password", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "handle", name="uq_bluesky_accounts_user_handle"),
    )

    op.add_column(
        "publishing_logs",
        sa.Column(
            "target_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("post_targets.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_publishing_logs_target_id",
        "publishing_logs",
        ["target_id"],
    )

    # --- Backfill: one post_targets row per non-draft/approved post. ---
    op.execute(
        sa.text(
            """
            INSERT INTO post_targets (
                post_id, platform, status, external_urn, published_at, created_at, updated_at
            )
            SELECT
                id,
                CAST('linkedin' AS platform),
                CAST('published' AS target_status),
                linkedin_urn,
                published_at,
                COALESCE(published_at, created_at),
                now()
            FROM posts
            WHERE status = 'published' AND linkedin_urn IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO post_targets (
                post_id, platform, status, error, created_at, updated_at
            )
            SELECT
                id,
                CAST('linkedin' AS platform),
                CAST('failed' AS target_status),
                error,
                now(),
                now()
            FROM posts
            WHERE status = 'failed'
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO post_targets (
                post_id, platform, status, scheduled_at, created_at, updated_at
            )
            SELECT
                id,
                CAST('linkedin' AS platform),
                CAST('pending' AS target_status),
                scheduled_at,
                now(),
                now()
            FROM posts
            WHERE status = 'scheduled' AND scheduled_at IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_publishing_logs_target_id", table_name="publishing_logs")
    op.drop_column("publishing_logs", "target_id")
    op.drop_table("bluesky_accounts")
    op.drop_table("post_targets")
    sa.Enum(name="target_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="platform").drop(op.get_bind(), checkfirst=True)
