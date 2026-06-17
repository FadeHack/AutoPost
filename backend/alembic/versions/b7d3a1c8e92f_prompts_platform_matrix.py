"""prompts platform matrix: add prompts.platform + (name, platform, version) unique

Revision ID: b7d3a1c8e92f
Revises: a3c8e0f5471b
Create Date: 2026-06-16 20:00:00.000000

Phase 12 Chunk A. Restructures `prompts` for a (category x platform) matrix so
the same draft category can produce a long LinkedIn post, a 280-char Bluesky
line, a 500-char Threads post, etc. — each driven by its own DB prompt instead
of the hardcoded inline `compress_for_<platform>` stopgap from Phase 11.

- Add nullable `platform` enum column (reuses the existing `platform` enum type
  created by the post_targets migration; create_type=False so we don't try to
  recreate it).
- Backfill every existing prompt row to `platform='linkedin'` — the current 4
  category prompts ARE the LinkedIn voice.
- Swap the old `uq_prompts_name_version` unique constraint for
  `uq_prompts_name_platform_version` so per-platform variants of the same
  (name, version) coexist.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d3a1c8e92f"
down_revision: Union[str, None] = "a3c8e0f5471b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Reuse the enum type already created by the post_targets migration.
_platform_enum = postgresql.ENUM(
    "linkedin",
    "bluesky",
    "mastodon",
    "threads",
    "instagram",
    name="platform",
    create_type=False,
)


def upgrade() -> None:
    op.add_column(
        "prompts",
        sa.Column("platform", _platform_enum, nullable=True),
    )
    # Existing rows are the LinkedIn voice prompts.
    op.execute("UPDATE prompts SET platform = 'linkedin'")

    op.drop_constraint("uq_prompts_name_version", "prompts", type_="unique")
    op.create_unique_constraint(
        "uq_prompts_name_platform_version",
        "prompts",
        ["name", "platform", "version"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_prompts_name_platform_version", "prompts", type_="unique"
    )
    op.create_unique_constraint(
        "uq_prompts_name_version", "prompts", ["name", "version"]
    )
    op.drop_column("prompts", "platform")
