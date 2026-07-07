"""tighten the X rewrite prompts to aim well under the 280 cap

Revision ID: a2c5e8f1b4d7
Revises: f4a9c2e7b1d6
Create Date: 2026-07-08 12:00:00.000000

The X rewrite over-shot 280 on dense sources because the prompt aimed for "under
275" — only 5 chars below the real 280 cap — while the model's natural landing
spot for a short-microblog rewrite is the 280–300 band. (Bluesky rarely trips
its own 300 cap precisely because its prompt aims for "under 280", a full 20
chars of headroom.)

This gives X the same proportional buffer: the prompt now aims for ~240 chars
(treating 250 as the ceiling), so the first pass lands under 280 far more often
and the run_platform_rewrite shorten-retry rarely has to fire. In-place UPDATE of
the 8 v1 X prompt bodies (anchors unchanged from e1f8b3c6a4d9).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2c5e8f1b4d7"
down_revision: Union[str, None] = "f4a9c2e7b1d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- New (tighter-target) X rewrite builder ---
def _x_new(audience: str, anchor: str) -> str:
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
        "- 0-1 lowercase hashtags at the end, or zero (X hashtags add little — "
        "prefer zero, and never let one push you near the limit).\n"
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

# The exact "under 275" text the previous version generated (for a clean downgrade).
def _x_old(audience: str, anchor: str) -> str:
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


def _apply(builder) -> None:
    conn = op.get_bind()
    stmt = sa.text(
        "UPDATE prompts SET body = :body "
        "WHERE name = :name AND platform::text = 'x' AND version = 1"
    )
    for name, spec in _CATEGORIES.items():
        conn.execute(
            stmt,
            {"name": name, "body": builder(spec["audience"], spec["anchor"])},
        )


def upgrade() -> None:
    _apply(_x_new)


def downgrade() -> None:
    _apply(_x_old)
