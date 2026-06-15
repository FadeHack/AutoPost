"""Publisher abstraction shared by all platform impls.

Each platform implements `Publisher.publish` — the platform-agnostic
orchestrator in `orchestrator.py` owns the retry loop, status flips, and
`PublishingLog` rows. The split:

  Orchestrator (platform-agnostic)        Publisher impl (platform-specific)
  ──────────────────────────────────      ─────────────────────────────────
  load target + post + account            char_limit, max_images constants
  select assets (carousel-aware)          download + upload images
  build raw commentary                    build payload + send POST
  status: publishing → published|failed   classify HTTP errors
  retry with backoff                      return external_urn

Adding a new platform = add an enum value to `Platform`, a Publisher subclass
here, and register it in `_REGISTRY`. No orchestrator changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GeneratedAsset, Post
from app.models.base import Platform


class PublishError(Exception):
    """Base error for the publisher layer. The orchestrator catches these,
    writes a PublishingLog row, and decides retry vs terminal-fail."""


class PermanentPublishError(PublishError):
    """Don't retry. Surface to operator (e.g. exceeds char limit, missing
    account, invalid payload)."""


class TransientPublishError(PublishError):
    """Worth a retry. Rate-limit, 5xx, network blip."""


class AuthPublishError(PublishError):
    """Token issue. Caller may attempt one forced refresh + single retry."""


@dataclass(frozen=True)
class PublishResult:
    """Successful publish outcome from a Publisher impl. The orchestrator
    persists these onto the PostTarget row."""
    external_urn: str
    raw_request: dict[str, Any]


class Publisher(ABC):
    """One implementation per Platform. Stateless apart from class-level
    constants — orchestrator instantiates fresh per attempt."""

    platform: ClassVar[Platform]
    # Hard cap for body+hashtags. Orchestrator gates BEFORE handing off and
    # raises PermanentPublishError with a clear message if exceeded.
    char_limit: ClassVar[int]
    # Number of images this platform attaches. Carousels beyond this are
    # truncated (operator pre-warned at approve time).
    max_images: ClassVar[int]
    # PDF/document carousel (LinkedIn-only). Default false.
    supports_documents: ClassVar[bool] = False

    @abstractmethod
    async def publish(
        self,
        *,
        session: AsyncSession,
        post: Post,
        account: Any,
        commentary: str,
        assets: list[GeneratedAsset],
    ) -> PublishResult:
        """Send the post to the platform. Returns the external URN + raw
        request payload on success; raises {Auth,Transient,Permanent}PublishError
        on failure. Implementations may mutate `account` (e.g. refresh tokens)
        — orchestrator commits after."""


# --- Registry ---


_REGISTRY: dict[Platform, type[Publisher]] = {}


def register(cls: type[Publisher]) -> type[Publisher]:
    """Class decorator: register a Publisher subclass for its platform.
    Importing the module is what triggers registration; orchestrator imports
    every concrete publisher at boot so all platforms self-register."""
    _REGISTRY[cls.platform] = cls
    return cls


def get_publisher_class(platform: Platform) -> type[Publisher]:
    if platform not in _REGISTRY:
        raise PermanentPublishError(
            f"no Publisher registered for platform '{platform.value}'"
        )
    return _REGISTRY[platform]
