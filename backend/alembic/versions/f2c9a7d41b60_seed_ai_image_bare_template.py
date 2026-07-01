"""seed ai_image_bare template (optional no-brand-frame AI image)

Revision ID: f2c9a7d41b60
Revises: e8b4c1f7d320
Create Date: 2026-07-01 00:00:00.000000

Registers the full-bleed AI-image template used when the operator turns the
brand frame OFF at render time. Same `ai_image` category as `ai_image_wrap`;
the renderer picks between them by name based on the request's `wrap` flag.
No new enum value needed — `ai_image` already exists.
"""
from __future__ import annotations

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "f2c9a7d41b60"
down_revision: Union[str, None] = "e8b4c1f7d320"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO templates (id, name, category, html_path, created_at, updated_at)
            VALUES (:id, :name, CAST(:category AS template_category), :html_path, now(), now())
            ON CONFLICT (name) DO NOTHING
            """
        ).bindparams(
            id=uuid4(),
            name="ai_image_bare",
            category="ai_image",
            html_path="ai_image_bare.html",
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM templates WHERE name = 'ai_image_bare'")
