"""Trends API.

- POST /trends/refresh — synchronous manual trigger (also runs on cron via
  the APScheduler retrieval_job; this is the "give me trends now" button).
- GET  /trends         — list trends, default unconsumed-first, newest first.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db import get_session
from app.models import Trend, User
from app.models.base import TrendSource
from app.retrieval.orchestrator import run_retrieval

router = APIRouter(prefix="/trends", tags=["trends"])


class RefreshResponse(BaseModel):
    fetched: int
    deduped: int
    inserted: int
    per_source: dict[str, int]


class TrendRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: TrendSource
    source_id: str
    title: str
    url: str
    summary: str | None
    score: int | None
    fetched_at: datetime
    consumed_at: datetime | None


class TrendPatch(BaseModel):
    consumed: bool


class BulkDeleteRequest(BaseModel):
    ids: list[UUID] = Field(..., min_length=1, max_length=500)


class BulkDeleteResponse(BaseModel):
    deleted: int


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(_: User = Depends(get_current_user)) -> RefreshResponse:
    summary = await run_retrieval()
    return RefreshResponse(**summary)


@router.get("", response_model=list[TrendRead])
async def list_trends(
    status: Literal["unconsumed", "consumed", "all"] = Query("unconsumed"),
    source: TrendSource | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list[TrendRead]:
    stmt = select(Trend).order_by(Trend.fetched_at.desc()).limit(limit)
    if status == "unconsumed":
        stmt = stmt.where(Trend.consumed_at.is_(None))
    elif status == "consumed":
        stmt = stmt.where(Trend.consumed_at.is_not(None))
    if source is not None:
        stmt = stmt.where(Trend.source == source)
    result = await session.execute(stmt)
    return [TrendRead.model_validate(r) for r in result.scalars().all()]


@router.patch("/{trend_id}", response_model=TrendRead)
async def update_trend(
    trend_id: UUID,
    patch: TrendPatch,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> TrendRead:
    trend = await session.get(Trend, trend_id)
    if trend is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="trend not found"
        )
    trend.consumed_at = datetime.now(timezone.utc) if patch.consumed else None
    await session.commit()
    await session.refresh(trend)
    return TrendRead.model_validate(trend)


@router.delete("/{trend_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_trend(
    trend_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> Response:
    trend = await session.get(Trend, trend_id)
    if trend is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="trend not found"
        )
    await session.delete(trend)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_trends(
    body: BulkDeleteRequest,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> BulkDeleteResponse:
    result = await session.execute(
        delete(Trend).where(Trend.id.in_(body.ids))
    )
    await session.commit()
    return BulkDeleteResponse(deleted=result.rowcount or 0)
