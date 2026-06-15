"""seed visual templates registry (Phase 4 rendering layer)

Revision ID: d8e2f4a91c56
Revises: b4e7c1f293a8
Create Date: 2026-05-30 18:00:00.000000

One row per HTML file under `backend/app/rendering/templates/`. `html_path` is
the filename only (relative to that dir), `name` is unique, `category` is the
visual-style enum (TemplateCategory: quote / insight / metric / carousel).

The renderer's `default_template_name_for_post()` maps PostCategory → one of
these `name`s. A user can also pick an explicit template via `template_id` on
`POST /posts/{id}/render`.

Adding a new template later = drop the HTML file in the templates dir and
write a one-row migration like this. No code deploy.
"""
from __future__ import annotations

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e2f4a91c56"
down_revision: Union[str, None] = "b4e7c1f293a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TEMPLATES = [
    {
        "name": "insight_card",
        "category": "insight",
        "html_path": "insight_card.html",
    },
    {
        "name": "quote_card",
        "category": "quote",
        "html_path": "quote_card.html",
    },
    {
        "name": "metric_card",
        "category": "metric",
        "html_path": "metric_card.html",
    },
    {
        "name": "carousel_slide",
        "category": "carousel",
        "html_path": "carousel_slide.html",
    },
]


def upgrade() -> None:
    template_category = sa.Enum(
        "quote",
        "insight",
        "metric",
        "carousel",
        name="template_category",
        create_type=False,
    )
    templates = sa.table(
        "templates",
        sa.column("id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("category", template_category),
        sa.column("html_path", sa.String),
        sa.column("thumbnail_url", sa.String),
    )
    rows = [
        {
            "id": uuid4(),
            "name": t["name"],
            "category": t["category"],
            "html_path": t["html_path"],
            "thumbnail_url": None,
        }
        for t in _TEMPLATES
    ]
    op.bulk_insert(templates, rows)


def downgrade() -> None:
    op.execute(
        "DELETE FROM templates WHERE name IN "
        "('insight_card', 'quote_card', 'metric_card', 'carousel_slide')"
    )
