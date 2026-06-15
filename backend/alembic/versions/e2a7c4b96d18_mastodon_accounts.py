"""mastodon_accounts (Phase 11 Chunk B)

Revision ID: e2a7c4b96d18
Revises: d4f6b8e1029c
Create Date: 2026-06-16 00:00:00.000000

Phase 11 Chunk B — Mastodon publisher.

New table `mastodon_accounts` — full OAuth (per-instance dynamic app
registration), access token Fernet-encrypted. No `expires_at`/`refresh_token`:
Mastodon access tokens don't expire by default and the standard flow issues no
refresh token. No backfill — the operator connects an account at runtime.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e2a7c4b96d18"
down_revision: Union[str, None] = "d4f6b8e1029c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mastodon_accounts",
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
        sa.Column("instance_url", sa.String(length=255), nullable=False),
        sa.Column("handle", sa.String(length=255), nullable=False),
        sa.Column("account_id", sa.String(length=255), nullable=False),
        sa.Column("access_token", sa.String(), nullable=False),
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
            "instance_url",
            "handle",
            name="uq_mastodon_accounts_user_instance_handle",
        ),
    )


def downgrade() -> None:
    op.drop_table("mastodon_accounts")
