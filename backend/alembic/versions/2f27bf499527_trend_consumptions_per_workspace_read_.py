"""trend_consumptions per-workspace read state

Revision ID: 2f27bf499527
Revises: 70117d5b9596
Create Date: 2026-08-16 20:59:42.151345

Trends stay a shared/global pool (one RSS+HN fetch serves every workspace),
but consumption becomes per-workspace: `trends.consumed_at` (one flag,
global) is replaced by `trend_consumptions(trend_id, workspace_id,
consumed_at)` so one workspace generating a draft from a trend doesn't
silently mark it consumed for every other workspace. No backfill — any
historical `consumed_at` values predate the retention-window tightening in
the same change (7 days) and would be stale within a day of deploy anyway;
every trend simply starts unconsumed for every workspace. `apscheduler_jobs`
is intentionally left alone — it's APScheduler-runtime-managed, not one of
our models, and autogenerate always tries to drop it (see the
`access_requests` migration for the same note).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2f27bf499527'
down_revision: Union[str, None] = '70117d5b9596'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('trend_consumptions',
    sa.Column('trend_id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['trend_id'], ['trends.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('trend_id', 'workspace_id')
    )
    op.drop_index('ix_trends_consumed_at', table_name='trends')
    op.drop_column('trends', 'consumed_at')


def downgrade() -> None:
    # Downgrade restores the schema only — per-workspace consumption rows
    # recorded after the upgrade are not translatable back into one global
    # flag and are dropped (same tradeoff as prior wipe-style downgrades in
    # this repo, e.g. d9a1c4e7f012).
    op.add_column('trends', sa.Column('consumed_at', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True))
    op.create_index('ix_trends_consumed_at', 'trends', ['consumed_at'], unique=False)
    op.drop_table('trend_consumptions')
