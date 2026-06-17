"""All ORM models. Importing this module registers every table on `Base.metadata`."""

from app.models.ai_generation import AIGeneration
from app.models.analytics import AnalyticsSnapshot
from app.models.base import (
    AccountKind,
    Base,
    Platform,
    PostCategory,
    PostStatus,
    PublishingStatus,
    TargetStatus,
    TemplateCategory,
    TimestampMixin,
    TrendSource,
    UserRole,
)
from app.models.bluesky_account import BlueskyAccount
from app.models.generated_asset import GeneratedAsset
from app.models.instagram_account import InstagramAccount
from app.models.linkedin_account import LinkedInAccount
from app.models.mastodon_account import MastodonAccount
from app.models.post import Post
from app.models.post_target import PostTarget
from app.models.prompt import Prompt
from app.models.threads_account import ThreadsAccount
from app.models.publishing_log import PublishingLog
from app.models.template import Template
from app.models.trend import Trend
from app.models.user import User

__all__ = [
    "Base",
    "TimestampMixin",
    "AccountKind",
    "Platform",
    "PostCategory",
    "PostStatus",
    "PublishingStatus",
    "TargetStatus",
    "TemplateCategory",
    "TrendSource",
    "UserRole",
    "User",
    "LinkedInAccount",
    "BlueskyAccount",
    "MastodonAccount",
    "ThreadsAccount",
    "InstagramAccount",
    "Trend",
    "Prompt",
    "Template",
    "Post",
    "PostTarget",
    "GeneratedAsset",
    "AIGeneration",
    "PublishingLog",
    "AnalyticsSnapshot",
]
