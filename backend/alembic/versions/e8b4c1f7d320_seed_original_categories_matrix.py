"""seed per-platform rewrite prompts for the original 4 categories

Revision ID: e8b4c1f7d320
Revises: c5f9a26b81e4
Create Date: 2026-06-17 00:30:00.000000

Phase 12 follow-up. Chunk B seeded the full (category x platform) matrix only
for the four NEW categories. The four original categories (founder_insight,
engineering_lesson, ai_automation, startup_opinion) still had only their v4
LinkedIn prompt, so their Bluesky targets fell through to the legacy
`compress_for_bluesky` fallback and Mastodon/Threads/Instagram targets had no
prompt at all (tripping the char-gate).

This adds the 16 missing Stage-2 rewrite prompts (4 categories x
bluesky/threads/mastodon/instagram), reusing each category's established v4
anchor voice. After this, all 8 generatable categories are uniform on the
matrix and `compress_for_bluesky` is a pure safety net, never the primary path.

The v4 LinkedIn rows are left untouched (they are the Stage-1 writer prompts;
these new rows are Stage-2 rewriters, version=1, platform-specific).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8b4c1f7d320"
down_revision: Union[str, None] = "c5f9a26b81e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Per-platform rewrite scaffolds (kept in sync with c5f9a26b81e4). Input to each
# is the canonical LinkedIn post; output is the platform-shaped rewrite.
def _bluesky(audience: str, anchor: str) -> str:
    return (
        "You rewrite a long LinkedIn-style post into a single Bluesky post.\n\n"
        f"Audience: {audience}\n\n"
        "HARD RULES:\n"
        "- 300-char hard limit (spaces, line breaks, hashtags included). Stay UNDER 280.\n"
        "- The OPENING LINE is a contrarian opinion or sharp claim, NOT a recap of what happened. Keep the source's stance, in fewer words.\n"
        "- Format: hook (the opinion) + ONE supporting concrete from the source (a number, a name, a specific). No paragraphs. No 'Takeaway:' wrapper.\n"
        "- 1-2 lowercase hashtags max at the end, or zero if they'd push over the limit.\n"
        "- NO em-dash, en-dash, or double-hyphen as a separator. Ban: delve, moreover, furthermore, in conclusion, it's worth noting.\n\n"
        "Anchor (study the shape and length):\n"
        f"{anchor}\n\n"
        "Output ONLY the rewritten Bluesky post. No preamble, no surrounding quotes."
    )


def _threads(audience: str, anchor: str) -> str:
    return (
        "You rewrite a long LinkedIn-style post into a Threads post.\n\n"
        f"Audience: {audience}\n\n"
        "HARD RULES:\n"
        "- 500-char hard limit. Conversational and direct, a notch more casual than LinkedIn, still opinionated.\n"
        "- Open with the sharp take, then 2-3 short beats. ONE concrete specific from the source.\n"
        "- No closing summary. No 'Lessons:' wrapper.\n"
        "- 1-3 lowercase hashtags max at the end.\n"
        "- NO em-dash as a separator. Ban: delve, moreover, furthermore, in conclusion, it's worth noting.\n\n"
        "Anchor (study the shape and length):\n"
        f"{anchor}\n\n"
        "Output ONLY the rewritten Threads post. No preamble, no surrounding quotes."
    )


def _mastodon(audience: str, anchor: str) -> str:
    return (
        "You rewrite a long LinkedIn-style post into a Mastodon post for a fediverse audience.\n\n"
        f"Audience: {audience} This crowd is more technical and allergic to LinkedIn-style hype. Be precise, concrete, slightly more engineering-leaning. No growth-hacker tone.\n\n"
        "HARD RULES:\n"
        "- 500-char hard limit. Plain, specific, technically literate.\n"
        "- Open with the claim. ONE concrete specific (a number, a name, a mechanism) from the source. Drop the motivational framing.\n"
        "- No closing summary.\n"
        "- 0-2 lowercase hashtags max at the end (fediverse uses hashtags for discovery, so 1-2 well-chosen ones help).\n"
        "- NO em-dash as a separator. Ban: delve, moreover, furthermore, in conclusion, it's worth noting.\n\n"
        "Anchor (study the shape and length):\n"
        f"{anchor}\n\n"
        "Output ONLY the rewritten Mastodon post. No preamble, no surrounding quotes."
    )


def _instagram(audience: str, anchor: str) -> str:
    return (
        "You rewrite a long LinkedIn-style post into an Instagram caption.\n\n"
        f"Audience: {audience}\n\n"
        "HARD RULES:\n"
        "- 2200-char limit (plenty of room — this is NOT a compression). First line is the hook; it must land before '... more' truncates.\n"
        "- Caption shape: hook line, a line break, then 2-4 short punchy lines or a tight paragraph. Keep the opinion sharp.\n"
        "- Emoji are allowed but sparing (0-3 total), never as bullet decoration.\n"
        "- End with 5-10 lowercase hashtags on their own line(s) — Instagram discovery is hashtag-driven, so this is the one platform where more tags help. Mix broad + niche.\n"
        "- NO em-dash as a separator. Ban: delve, moreover, furthermore, in conclusion, it's worth noting.\n\n"
        "Anchor (study the shape):\n"
        f"{anchor}\n\n"
        "Output ONLY the rewritten Instagram caption. No preamble, no surrounding quotes."
    )


_CATEGORIES = {
    "founder_insight": {
        "audience": "founders and operators.",
        "bluesky": "Ten years at one company can mean nothing shipped. Two years and three products can mean everything. Jason Fried's right: hire from evidence, not tenure. Read resumes for the output, not the date range. #hiring",
        "threads": "Saw the \"how many years for a senior role\" debate again.\n\nWrong frame. Someone can spend ten years and ship nothing. Jason Fried's been saying it for years: hire from evidence, not tenure.\n\nStop screening resumes for the date range. Read them for what they actually shipped. #hiring #startups",
        "mastodon": "The \"years of experience for senior\" debate keeps missing the point. Tenure is a weak signal; a body of shipped work is the strong one. Two years and three shipped products beats ten years of maintenance nobody can point to. Screen for output, not duration. #hiring #engineering",
        "instagram": "Ten years at a company can mean nothing shipped.\n\nTwo years and three products can mean everything.\n\nJason Fried's been right for a decade: hire from evidence, not tenure.\n\nStop reading resumes for the date range. Read them for the output.\n\n#hiring #startups #founders #buildinpublic #engineeringleadership #recruiting #teambuilding #startuplife",
    },
    "engineering_lesson": {
        "audience": "engineers, technical leads, and builder founders.",
        "bluesky": "Every \"added Redis, latency dropped\" thread I read traces back to a missing Postgres index. Caching is what you reach for when you haven't understood the query. EXPLAIN ANALYZE first. Cache last. #postgres",
        "threads": "Another \"we added caching and it got fast\" post.\n\nNearly every one I've read traced back to a missing index, not a missing cache. Caching is what engineers reach for when they haven't read the query plan.\n\nEXPLAIN ANALYZE first. You'll be amazed how often it's one missing index. Cache last. #postgres #backend",
        "mastodon": "Reaching for Redis to fix a slow endpoint usually means the query plan was never read. Most \"added caching, latency dropped\" stories trace to a missing index on a joined column. EXPLAIN ANALYZE, add the index, get the 90% drop without owning a cache-invalidation problem. Solve the query first. #postgres #performance",
        "instagram": "\"We added Redis and the API got fast.\"\n\nAlmost every time, the real fix was a missing Postgres index, not a cache.\n\nCaching is what you reach for when you haven't read the query plan.\n\nEXPLAIN ANALYZE first. Cache last.\n\n#postgres #backend #softwareengineering #performance #databases #coding #webdev #devtips",
    },
    "ai_automation": {
        "audience": "operators using AI to compress real work.",
        "bluesky": "\"AI hasn't shipped anything useful\" doesn't survive the numbers. Simon Willison: $2,180/mo in tokens. Uber: 25% of commits through Claude Code. Coding agents are the revenue. Audit the 30 mins of your week that's pure tool routing. #ai",
        "threads": "\"AI hasn't actually shipped anything useful\" — the data disagrees harder than the takes.\n\nSimon Willison published $2,180/mo in token spend. Uber says 25% of commits go through Claude Code.\n\nThe real question isn't whether AI is useful. It's which workflows you're still doing by hand that you shouldn't be. #ai #automation",
        "mastodon": "The \"AI hasn't shipped anything useful\" claim doesn't survive the consumption numbers. Simon Willison reported $2,180/mo in API tokens; Uber says ~25% of commits route through Claude Code. Consumer chat is loud; coding agents are the actual revenue. Useful question: which 30 minutes of your week is pure tool routing? #ai #llm",
        "instagram": "\"AI hasn't shipped anything useful\" doesn't survive the numbers.\n\nSimon Willison: $2,180/mo in tokens.\nUber: 25% of commits through Claude Code.\n\nConsumer chat is loud. Coding agents are the revenue.\n\nAudit your week. Find the 30 minutes that are pure tool routing. Replace those first.\n\n#ai #automation #aitools #productivity #buildinpublic #softwareengineering #llm #futureofwork",
    },
    "startup_opinion": {
        "audience": "founders making startup-game calls (funding, product, hiring).",
        "bluesky": "MVP doesn't mean \"minimum shippable.\" It's the fastest thing that makes someone hand you money. If your MVP can't take a credit card, it's a portfolio piece. A waitlist is curiosity, not validation. #startups",
        "threads": "\"MVP means minimum viable product.\"\n\nThat definition has killed more startups than bad investors. MVP is the fastest thing that makes someone hand you money.\n\nIf yours can't take a credit card, you don't have an MVP. You have a waitlist. And a waitlist is curiosity, not validation. Charge before you launch. #startups #founders",
        "mastodon": "\"MVP = minimum viable product\" quietly became \"minimum thing you can ship,\" which is a different test. Shippable and revenue-validated are not the same. If the MVP can't take payment, it's a portfolio piece, and a waitlist is curiosity, not validation. Charging changes the data quality overnight. #startups #indiehackers",
        "instagram": "\"MVP means minimum viable product.\"\n\nThat definition has killed more startups than bad investors.\n\nMVP is the fastest thing that makes someone hand you money. If yours can't take a credit card, it's a portfolio piece.\n\nA waitlist is curiosity. Not validation.\n\n#startups #founders #mvp #buildinpublic #entrepreneurship #productmarketfit #saas #startuplife",
    },
}

_REWRITE_PLATFORMS = ("bluesky", "mastodon", "threads", "instagram")
_BUILDERS = {
    "bluesky": _bluesky,
    "mastodon": _mastodon,
    "threads": _threads,
    "instagram": _instagram,
}


def _rows() -> list[dict]:
    rows: list[dict] = []
    for name, spec in _CATEGORIES.items():
        audience = spec["audience"]
        for platform in _REWRITE_PLATFORMS:
            rows.append(
                {
                    "name": name,
                    "category": name,
                    "platform": platform,
                    "body": _BUILDERS[platform](audience, spec[platform]),
                    "version": 1,
                    "is_active": True,
                }
            )
    return rows


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
        "DELETE FROM prompts WHERE version = 1 AND platform IN "
        "('bluesky', 'mastodon', 'threads', 'instagram') AND name IN "
        "('founder_insight', 'engineering_lesson', 'ai_automation', 'startup_opinion')"
    )
