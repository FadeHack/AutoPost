"""add_render_kind_to_generated_assets

Revision ID: 8a3180a8960e
Revises: 559724258d97
Create Date: 2026-06-13 00:00:00.000000

Phase 10 — AI image generation add-on. Distinguishes templated cards (default,
existing path) from AI-generated images (Flux via Cloudflare/Pollinations).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8a3180a8960e'
down_revision: Union[str, None] = '559724258d97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    render_kind = sa.Enum('template', 'ai_image', name='renderkind')
    render_kind.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'generated_assets',
        sa.Column(
            'render_kind',
            render_kind,
            nullable=False,
            server_default='template',
        ),
    )


def downgrade() -> None:
    op.drop_column('generated_assets', 'render_kind')
    sa.Enum(name='renderkind').drop(op.get_bind(), checkfirst=True)
