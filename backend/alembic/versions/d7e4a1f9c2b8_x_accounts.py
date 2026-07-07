"""x_accounts + platform enum 'x' (Phase 11 Chunk F)

Revision ID: d7e4a1f9c2b8
Revises: a3d1e6f92c74
Create Date: 2026-07-08 10:00:00.000000

Phase 11 Chunk F — X (Twitter) publisher, full X API v2 integration.

Two changes:
  1. Add `'x'` to the `platform` Postgres enum so `post_targets.platform` and
     `prompts.platform` can carry X. Added inside an `autocommit_block` so the
     follow-up seed migration (which INSERTs prompts with platform='x') can
     reference the value — Postgres forbids using an enum value added by
     `ALTER TYPE ... ADD VALUE` in the same transaction, and Alembic runs the
     whole upgrade in one transaction.
  2. New `x_accounts` table — OAuth 2.0 Authorization Code + PKCE against a
     single fixed X app. UNLIKE the other platforms, the access token is
     short-lived (~2h) and X issues a rotating refresh token (offline.access),
     so BOTH `access_token` and `refresh_token` are stored Fernet-encrypted with
     `expires_at`. No backfill — the operator connects an account at runtime
     once a paid X app is provisioned (the API has no free tier).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d7e4a1f9c2b8"
down_revision: Union[str, None] = "a3d1e6f92c74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Commit the enum value before the (later) seed migration references it.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform ADD VALUE IF NOT EXISTS 'x'")

    op.create_table(
        "x_accounts",
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
        sa.Column("x_user_id", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("access_token", sa.String(), nullable=False),
        sa.Column("refresh_token", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "user_id",
            "x_user_id",
            name="uq_x_accounts_user_x_user",
        ),
    )


def downgrade() -> None:
    # Postgres can't cleanly DROP an enum value; leave 'x' on the type.
    op.drop_table("x_accounts")
