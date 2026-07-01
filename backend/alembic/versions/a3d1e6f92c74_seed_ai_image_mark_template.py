"""seed ai_image_mark template (lighter-touch corner brand mark)

Revision ID: a3d1e6f92c74
Revises: f2c9a7d41b60
Create Date: 2026-07-01 00:10:00.000000

Registers the third AI-image frame: a full-bleed Flux image with just a small
Nestwhirr brand mark in the corner (no full black card). Same `ai_image`
category; the renderer picks card/mark/bare by name off the request `frame`.
"""
from __future__ import annotations

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "a3d1e6f92c74"
down_revision: Union[str, None] = "f2c9a7d41b60"
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
            name="ai_image_mark",
            category="ai_image",
            html_path="ai_image_mark.html",
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM templates WHERE name = 'ai_image_mark'")
