"""Fetcher ABC + TrendItem dataclass.

Every retrieval source implements `Fetcher` and yields `TrendItem`s.
The orchestrator normalizes, dedupes, and persists them to `trends`.
Sources never touch the DB directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.base import TrendSource


@dataclass
class TrendItem:
    source: TrendSource
    source_id: str
    title: str
    url: str
    summary: str | None = None
    score: float | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime | None = None


class Fetcher(ABC):
    source: TrendSource

    @abstractmethod
    async def fetch(self) -> list[TrendItem]:
        """Pull the latest items. Must be idempotent and side-effect-free."""
        ...
