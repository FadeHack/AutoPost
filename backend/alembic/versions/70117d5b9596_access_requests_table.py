"""access_requests table

Revision ID: 70117d5b9596
Revises: d9a1c4e7f012
Create Date: 2026-07-20 17:37:06.914835

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '70117d5b9596'
down_revision: Union[str, None] = 'd9a1c4e7f012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: `apscheduler_jobs` is a runtime-managed table (APScheduler's
    # SQLAlchemyJobStore creates it on startup) — not in our models, so
    # autogenerate wants to drop it. Left untouched here on purpose.
    op.create_table('access_requests',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('company', sa.String(length=255), nullable=True),
    sa.Column('reason', sa.String(length=2000), nullable=True),
    sa.Column('status', sa.Enum('pending', 'approved', 'denied', name='access_request_status'), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reviewed_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_access_requests_email'), 'access_requests', ['email'], unique=False)
    op.create_index(op.f('ix_access_requests_status'), 'access_requests', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_access_requests_status'), table_name='access_requests')
    op.drop_index(op.f('ix_access_requests_email'), table_name='access_requests')
    op.drop_table('access_requests')
    # The Enum type is created implicitly by create_table; drop it so a
    # re-upgrade doesn't collide with a leftover type.
    sa.Enum(name='access_request_status').drop(op.get_bind(), checkfirst=True)
