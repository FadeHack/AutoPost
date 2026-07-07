"""seed the X (Twitter) per-platform rewrite prompts

Revision ID: e1f8b3c6a4d9
Revises: d7e4a1f9c2b8
Create Date: 2026-07-08 10:05:00.000000

Phase 11 Chunk F follow-up — add X to the per-platform prompt matrix.

X is a short microblog, so its rewrite prompt is Bluesky-shaped: a 280-char hard
cap, hook-as-opinion, one concrete specific, minimal hashtags. This seeds one
Stage-2 rewrite prompt per generatable category (8 total: the original 4 +
Phase-12's 4). The anchors reuse each category's established Bluesky anchor
(already tuned to ~280 chars), keeping the voice consistent with the other
microblog targets. After this, all 8 categories are uniform across
linkedin/bluesky/mastodon/threads/instagram/x.

Depends on `d7e4a1f9c2b8` having committed the `'x'` platform enum value.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f8b3c6a4d9"
down_revision: Union[str, None] = "d7e4a1f9c2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _x(audience: str, anchor: str) -> str:
    return (
        "You rewrite a long LinkedIn-style post into a single X (Twitter) post.\n\n"
        f"Audience: {audience}\n\n"
        "HARD RULES:\n"
        "- 280-char hard limit (spaces, line breaks, hashtags included). Stay UNDER 275.\n"
        "- The OPENING LINE is a contrarian opinion or sharp claim, NOT a recap of what happened. Keep the source's stance, in fewer words. It has to earn the tap.\n"
        "- Format: hook (the opinion) + ONE supporting concrete from the source (a number, a name, a specific). Tight. No 'Takeaway:' wrapper.\n"
        "- 0-2 lowercase hashtags max at the end, or zero if they'd push over the limit (X hashtags add little — prefer zero unless one is genuinely on-topic).\n"
        "- NO em-dash, en-dash, or double-hyphen as a separator. Ban: delve, moreover, furthermore, in conclusion, it's worth noting.\n\n"
        "Anchor (study the shape and length):\n"
        f"{anchor}\n\n"
        "Output ONLY the rewritten X post. No preamble, no surrounding quotes."
    )


# (category, audience, X anchor) — anchors reuse each category's Bluesky anchor.
_CATEGORIES: dict[str, dict[str, str]] = {
    "founder_insight": {
        "audience": "founders and operators.",
        "anchor": "Ten years at one company can mean nothing shipped. Two years and three products can mean everything. Jason Fried's right: hire from evidence, not tenure. Read resumes for the output, not the date range.",
    },
    "engineering_lesson": {
        "audience": "engineers, technical leads, and builder founders.",
        "anchor": "Every \"added Redis, latency dropped\" thread I read traces back to a missing Postgres index. Caching is what you reach for when you haven't understood the query. EXPLAIN ANALYZE first. Cache last.",
    },
    "ai_automation": {
        "audience": "operators using AI to compress real work.",
        "anchor": "\"AI hasn't shipped anything useful\" doesn't survive the numbers. Simon Willison: $2,180/mo in tokens. Uber: 25% of commits through Claude Code. Coding agents are the revenue, not the chatbots.",
    },
    "startup_opinion": {
        "audience": "founders making startup-game calls (funding, product, hiring).",
        "anchor": "MVP doesn't mean \"minimum shippable.\" It's the fastest thing that makes someone hand you money. If your MVP can't take a credit card, it's a portfolio piece. A waitlist is curiosity, not validation.",
    },
    "dev_tooling": {
        "audience": "staff engineers, EMs, and platform teams.",
        "anchor": "Internal platforms don't fail on tech. They fail on adoption. Will Larson's right: a tool nobody chose is a hobby with a budget line. Build the one teams opt into.",
    },
    "pricing_business_model": {
        "audience": "founders and operators thinking about pricing and packaging.",
        "anchor": "A free tier isn't a cost center. It's a distribution channel you're funding. Ben Thompson's aggregation point: own the demand side and free becomes the moat, not the discount.",
    },
    "product_postmortem": {
        "audience": "engineers and SREs who run real systems.",
        "anchor": "\"Engineer pushed a bad config\" is where the investigation stopped, not the root cause. The bug is the system that let one unreviewed change hit every host with no canary. Fix the system, not the person.",
    },
    "design_thinking": {
        "audience": "designers, PMs, and founders who care about product quality.",
        "anchor": "Design isn't how it looks. It's the decisions about how it works. Julie Zhuo's been right for a decade: hand design the spec after the decisions are made and you get decoration, not design.",
    },
}


def _rows() -> list[dict]:
    return [
        {
            "name": name,
            "category": name,
            "platform": "x",
            "body": _x(spec["audience"], spec["anchor"]),
            "version": 1,
            "is_active": True,
        }
        for name, spec in _CATEGORIES.items()
    ]


def upgrade() -> None:
    prompts = sa.table(
        "prompts",
        sa.column("name", sa.String),
        sa.column("category", sa.Enum(name="post_category")),
        sa.column("platform", sa.Enum(name="platform")),
        sa.column("body", sa.String),
        sa.column("version", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(prompts, _rows())


def downgrade() -> None:
    op.execute(
        "DELETE FROM prompts WHERE version = 1 AND platform = 'x'"
    )
