"""All ORM models. Importing this module registers every table on `Base.metadata`."""

from app.models.ai_generation import AIGeneration
from app.models.analytics import AnalyticsSnapshot
from app.models.base import (
    AccountKind,
    Base,
    PostCategory,
    PostStatus,
    PublishingStatus,
    TemplateCategory,
    TimestampMixin,
    TrendSource,
    UserRole,
)
from app.models.generated_asset import GeneratedAsset
from app.models.linkedin_account import LinkedInAccount
from app.models.post import Post
from app.models.prompt import Prompt
from app.models.publishing_log import PublishingLog
from app.models.template import Template
from app.models.trend import Trend
from app.models.user import User

__all__ = [
    "Base",
    "TimestampMixin",
    "AccountKind",
    "PostCategory",
    "PostStatus",
    "PublishingStatus",
    "TemplateCategory",
    "TrendSource",
    "UserRole",
    "User",
    "LinkedInAccount",
    "Trend",
    "Prompt",
    "Template",
    "Post",
    "GeneratedAsset",
    "AIGeneration",
    "PublishingLog",
    "AnalyticsSnapshot",
]
