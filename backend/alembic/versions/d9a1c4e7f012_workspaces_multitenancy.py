"""workspaces_multitenancy

Revision ID: d9a1c4e7f012
Revises: c7f1a4d90e23
Create Date: 2026-07-20 00:00:00.000000

Phase 14 Chunk B — per-workspace multi-tenancy.

Introduces the `workspaces` tenant boundary and scopes the private data tables by
`workspace_id`:
  - PRIVATE (per workspace): posts (+ downstream via post_id) + the 6 social-account
    tables (linkedin/x/bluesky/mastodon/threads/instagram).
  - SHARED (unchanged): trends, prompts, templates.

**DESTRUCTIVE — this migration WIPES all existing posts and connected social accounts**
(user-approved 2026-07-20 relaunch). Existing posts have no owner column, so there is
no correct way to assign them to a workspace; the accounts belonged to a stray test
user. Rather than guess, we truncate the private tables and start clean. Each existing
`users` row gets its own fresh workspace so nobody is orphaned (1 user / workspace).
Trends/prompts/templates are preserved.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = 'd9a1c4e7f012'
down_revision: Union[str, None] = 'c7f1a4d90e23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACCOUNT_TABLES = (
    "linkedin_accounts",
    "x_accounts",
    "bluesky_accounts",
    "mastodon_accounts",
    "threads_accounts",
    "instagram_accounts",
)


def upgrade() -> None:
    conn = op.get_bind()

    # 1. workspaces table.
    op.create_table(
        "workspaces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # 2. users.workspace_id (nullable first so we can backfill).
    op.add_column(
        "users",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_users_workspace_id", "users", ["workspace_id"])
    op.create_foreign_key(
        "fk_users_workspace_id", "users", "workspaces", ["workspace_id"], ["id"], ondelete="RESTRICT"
    )

    # 3. One fresh workspace per existing user (name = email local part).
    users = conn.execute(sa.text("SELECT id, email FROM users")).fetchall()
    for u in users:
        name = (u.email or "workspace").split("@")[0] or "workspace"
        ws_id = conn.execute(
            sa.text("INSERT INTO workspaces (name) VALUES (:n) RETURNING id"), {"n": name}
        ).scalar()
        conn.execute(
            sa.text("UPDATE users SET workspace_id = :w WHERE id = :u"), {"w": ws_id, "u": u.id}
        )

    # 4. Now every user has a workspace → enforce NOT NULL.
    op.alter_column("users", "workspace_id", nullable=False)

    # 5. WIPE the private data (see module docstring). CASCADE clears post children
    #    (post_targets, generated_assets, publishing_logs, analytics, ai_generations).
    op.execute(
        "TRUNCATE TABLE posts, " + ", ".join(_ACCOUNT_TABLES) + " RESTART IDENTITY CASCADE"
    )

    # 6. Add workspace_id (NOT NULL) to the now-empty private tables.
    for table in ("posts", *_ACCOUNT_TABLES):
        op.add_column(
            table,
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        )
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])
        op.create_foreign_key(
            f"fk_{table}_workspace_id", table, "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    # Note: the wiped posts/accounts cannot be restored; this only reverses the schema.
    for table in ("posts", *_ACCOUNT_TABLES):
        op.drop_constraint(f"fk_{table}_workspace_id", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        op.drop_column(table, "workspace_id")

    op.drop_constraint("fk_users_workspace_id", "users", type_="foreignkey")
    op.drop_index("ix_users_workspace_id", table_name="users")
    op.drop_column("users", "workspace_id")

    op.drop_table("workspaces")
