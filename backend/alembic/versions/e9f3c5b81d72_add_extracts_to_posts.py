"""add posts.extracts JSONB for per-template content (Phase 4 Chunk D)

Revision ID: e9f3c5b81d72
Revises: d8e2f4a91c56
Create Date: 2026-05-30 19:00:00.000000

`extracts` holds the Stage 4 LLM output: a pull quote (for quote_card), a
headline metric value + label (for metric_card), and a carousel slide
breakdown (for carousel_slide).

Shape (nullable; existing rows stay NULL until re-rendered):
  {
    "pull_quote": "string | null",
    "metric_value": "string | null",
    "metric_label": "string | null",
    "carousel_slides": [{"text": "string"}, ...]   // 3-5 slides
  }

We keep it JSONB rather than 4 separate columns so adding new per-template
fields later (e.g. an OG-card subtitle) is a code change, not a migration.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e9f3c5b81d72"
down_revision: Union[str, None] = "d8e2f4a91c56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("extracts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("posts", "extracts")
