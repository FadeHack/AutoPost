"""target_status enum 'skipped' (manual-post legs)

Revision ID: f4a9c2e7b1d6
Revises: e1f8b3c6a4d9
Create Date: 2026-07-08 11:00:00.000000

Adds `'skipped'` to the `target_status` Postgres enum. A skipped PostTarget is
one whose platform is enabled for content generation but has no API account
connected, so the publish fan-out intentionally did NOT attempt it (the operator
posts it by hand — e.g. X while not connected). It's terminal and non-failing;
the orchestrator's post-status aggregation ignores skipped legs.

Added inside an `autocommit_block` (Postgres forbids using an enum value added by
`ALTER TYPE ... ADD VALUE` in the same transaction; Alembic runs the upgrade in
one transaction).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "f4a9c2e7b1d6"
down_revision: Union[str, None] = "e1f8b3c6a4d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE target_status ADD VALUE IF NOT EXISTS 'skipped'")


def downgrade() -> None:
    # Postgres can't cleanly DROP an enum value; leave 'skipped' on the type.
    pass
