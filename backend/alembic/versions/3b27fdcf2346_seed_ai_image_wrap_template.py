"""seed ai_image_wrap template + add TemplateCategory enum value

Revision ID: 3b27fdcf2346
Revises: 8a3180a8960e
Create Date: 2026-06-13 00:30:00.000000

Phase 10 Chunk D — adds the brand-wrap template that composites a Flux-generated
image inside the Nestwhirr minimal-dark identity (eyebrow + 800x800 inset +
brand strap), and registers it in the templates table.

ALTER TYPE ... ADD VALUE cannot run inside a transaction, hence
`op.execute("COMMIT")` before the ALTER (sqlalchemy autocommit).
"""
from __future__ import annotations

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "3b27fdcf2346"
down_revision: Union[str, None] = "8a3180a8960e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE must run outside any transaction.
    op.execute("COMMIT")
    op.execute("ALTER TYPE template_category ADD VALUE IF NOT EXISTS 'ai_image'")

    op.execute(
        sa.text(
            """
            INSERT INTO templates (id, name, category, html_path, created_at, updated_at)
            VALUES (:id, :name, CAST(:category AS template_category), :html_path, now(), now())
            ON CONFLICT (name) DO NOTHING
            """
        ).bindparams(
            id=uuid4(),
            name="ai_image_wrap",
            category="ai_image",
            html_path="ai_image_wrap.html",
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM templates WHERE name = 'ai_image_wrap'")
    # Postgres does not support DROP VALUE on an enum type. The 'ai_image'
    # value stays in the type definition — harmless, no rows reference it.
