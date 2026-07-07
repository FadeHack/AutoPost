"""X rewrite prompts: require 1-2 relevant hashtags (data-backed optimum)

Revision ID: b3d6f9a2c5e8
Revises: a2c5e8f1b4d7
Create Date: 2026-07-08 12:30:00.000000

The previous tighten (a2c5e8f1b4d7) said "0-1 hashtags, prefer zero" on the
assumption that X hashtags add nothing. Web-verified (2026): 1-2 relevant
hashtags earn ~21% MORE engagement than zero; only 3+ get penalized (spam
classifier). Hashtags are no longer needed for topic classification (X ranks on
semantic embeddings now), but 1-2 still help reach. So swap the rule to
"exactly 1-2 relevant lowercase hashtags", hard-ceiling 2.

In-place UPDATE of the 8 v1 X prompt bodies; only the hashtag rule changes vs
a2c5e8f1b4d7 (length target + everything else identical). Anchors unchanged.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3d6f9a2c5e8"
down_revision: Union[str, None] = "a2c5e8f1b4d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_HASHTAG_RULE_NEW = (
    "- End with 1-2 relevant lowercase hashtags (on X this is the engagement "
    "sweet spot — 1-2 beats zero, but 3+ trips the spam penalty, so NEVER more "
    "than 2). Make them specific and on-topic, not generic filler.\n"
)
_HASHTAG_RULE_OLD = (
    "- 0-1 lowercase hashtags at the end, or zero (X hashtags add little — "
    "prefer zero, and never let one push you near the limit).\n"
)


def _x(audience: str, anchor: str, hashtag_rule: str) -> str:
    return (
        "You rewrite a long LinkedIn-style post into a single X (Twitter) post.\n\n"
        f"Audience: {audience}\n\n"
        "HARD RULES:\n"
        "- LENGTH IS THE #1 CONSTRAINT. Aim for about 240 characters; treat 250 "
        "as your ceiling (spaces, line breaks, hashtags all count). 280 is the "
        "absolute hard limit and anything over it is UNUSABLE — being comfortably "
        "under is always better than being clever and long.\n"
        "- The OPENING LINE is a contrarian opinion or sharp claim, NOT a recap of "
        "what happened. Keep the source's stance, in fewer words. It has to earn the tap.\n"
        "- Format: hook (the opinion) + ONE supporting concrete from the source (a "
        "number, a name, a specific). Pick the SINGLE strongest concrete and drop "
        "the rest — do not try to keep every detail. Tight. No 'Takeaway:' wrapper.\n"
        f"{hashtag_rule}"
        "- NO em-dash, en-dash, or double-hyphen as a separator. Ban: delve, "
        "moreover, furthermore, in conclusion, it's worth noting.\n\n"
        "Anchor (study the shape and length — this is about the right size):\n"
        f"{anchor}\n\n"
        "Output ONLY the rewritten X post. No preamble, no surrounding quotes."
    )


# (category, audience, anchor) — anchors unchanged from e1f8b3c6a4d9.
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


def _apply(hashtag_rule: str) -> None:
    conn = op.get_bind()
    stmt = sa.text(
        "UPDATE prompts SET body = :body "
        "WHERE name = :name AND platform::text = 'x' AND version = 1"
    )
    for name, spec in _CATEGORIES.items():
        conn.execute(
            stmt,
            {
                "name": name,
                "body": _x(spec["audience"], spec["anchor"], hashtag_rule),
            },
        )


def upgrade() -> None:
    _apply(_HASHTAG_RULE_NEW)


def downgrade() -> None:
    _apply(_HASHTAG_RULE_OLD)
