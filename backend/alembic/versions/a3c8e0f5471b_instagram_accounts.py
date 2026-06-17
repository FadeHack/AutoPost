"""instagram_accounts (Phase 11 Chunk D)

Revision ID: a3c8e0f5471b
Revises: f1b3d7a8e564
Create Date: 2026-06-16 14:00:00.000000

Phase 11 Chunk D — Instagram publisher (Meta-gated).

New table `instagram_accounts` — Meta **Instagram Login** flow (NOT Facebook
Login) against a single fixed Instagram app. Long-lived access token (60 days)
Fernet-encrypted; `expires_at` present (token refreshes in place via
ig_refresh_token, no separate refresh_token). No backfill — the operator
connects a Creator/Business account at runtime once Meta App Review clears.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a3c8e0f5471b"
down_revision: Union[str, None] = "f1b3d7a8e564"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "instagram_accounts",
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
        sa.Column("instagram_user_id", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("access_token", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("account_type", sa.String(length=64), nullable=True),
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
            "instagram_user_id",
            name="uq_instagram_accounts_user_ig_user",
        ),
    )


def downgrade() -> None:
    op.drop_table("instagram_accounts")
