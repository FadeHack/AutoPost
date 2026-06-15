"""add_slide_index_to_generated_assets

Revision ID: 559724258d97
Revises: e9f3c5b81d72
Create Date: 2026-06-03 00:22:59.291098

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '559724258d97'
down_revision: Union[str, None] = 'e9f3c5b81d72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'generated_assets',
        sa.Column('slide_index', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('generated_assets', 'slide_index')
