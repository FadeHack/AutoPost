"""post_targets.commentary — per-platform body override

Revision ID: d4f6b8e1029c
Revises: c9e1f02db4a7
Create Date: 2026-06-16 00:00:00.000000

Phase 11 Chunk A follow-up: platform selection moves pre-generation. The
generator runs a per-platform Stage 2 rewrite so a long-form LinkedIn essay
and a 300-char Bluesky line both ship at publish time without the orchestrator
failing the char-limit gate.

`commentary` is NULL for the canonical platform (orchestrator falls back to
building from Post.hook/body/tags). For non-canonical platforms (currently:
Bluesky) the generator stores the platform-specific rewrite here. Existing
rows stay NULL — orchestrator's fallback path handles them.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4f6b8e1029c"
down_revision: Union[str, None] = "c9e1f02db4a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "post_targets",
        sa.Column("commentary", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("post_targets", "commentary")
