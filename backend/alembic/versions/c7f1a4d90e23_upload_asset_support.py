"""upload_asset_support

Revision ID: c7f1a4d90e23
Revises: b3d6f9a2c5e8
Create Date: 2026-07-13 00:00:00.000000

Custom-image upload path. Adds a third `renderkind` value ('upload') for
operator-uploaded images that post exactly as uploaded (raw passthrough, no
Playwright render, no template) and relaxes `generated_assets.template_id` to
nullable so those rows can carry NULL. Every rendered row (template / ai_image)
still sets a valid template_id.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c7f1a4d90e23'
down_revision: Union[str, None] = 'b3d6f9a2c5e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres forbids using an enum value added by ALTER TYPE in the same
    # transaction, and Alembic wraps the whole upgrade in one. Commit the new
    # value in its own autocommit block so later work (and app code) can use it.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE renderkind ADD VALUE IF NOT EXISTS 'upload'")

    op.alter_column('generated_assets', 'template_id', nullable=True)


def downgrade() -> None:
    # Uploaded rows have NULL template_id; they'd violate the restored NOT NULL.
    # Drop them first (they're just marketing artifacts, re-uploadable), then
    # re-tighten. The 'upload' enum value is left in place — Postgres can't
    # cleanly DROP an enum value.
    op.execute(
        "DELETE FROM generated_assets WHERE render_kind = 'upload'"
    )
    op.alter_column('generated_assets', 'template_id', nullable=False)
