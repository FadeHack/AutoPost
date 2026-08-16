"""Trends API.

- POST /trends/refresh    — synchronous manual trigger (also runs on cron via
  the APScheduler retrieval_job; this is the "give me trends now" button).
- GET  /trends            — list trends, default unconsumed-first, newest first.
- PATCH /trends/{id}      — toggle consumed for the caller's workspace.
- POST /trends/dismiss-all — bulk-consume everything matching a filter, no
  id list / pagination required (the fix for "I have to Load More five times
  to clear my inbox").
- DELETE /trends/{id}     — admin-only hard delete. Trends are a SHARED pool
  (CLAUDE.md); removing a row here removes it for every workspace, so this
  is no longer a plain-editor action (2026-08-16). Regular cleanup happens
  via the automatic retention sweep (`scheduler/jobs.py::trend_retention_job`)
  and everyday "clear my inbox" happens via dismiss, which only touches the
  caller's own read-state and never deletes the shared row.

Consumption is per-workspace (`TrendConsumption`), not a column on `Trend` —
see CONTEXT.md's 2026-08-16 entry for the full rationale.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_current_workspace, require_admin
from app.db import get_session
from app.models import Trend, TrendConsumption, User
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


class DismissAllResponse(BaseModel):
    dismissed: int
    # Refill page for the active filter, returned in the same round-trip so
    # the client never has to fire a second GET /trends after dismissing.
    next: list[TrendRead] = Field(default_factory=list)


def _row_to_read(trend: Trend, consumed_at: datetime | None) -> TrendRead:
    return TrendRead(
        id=trend.id,
        source=trend.source,
        source_id=trend.source_id,
        title=trend.title,
        url=trend.url,
        summary=trend.summary,
        score=trend.score,
        fetched_at=trend.fetched_at,
        consumed_at=consumed_at,
    )


async def _query_trends(
    session: AsyncSession,
    workspace_id: UUID,
    status: Literal["unconsumed", "consumed", "all"],
    source: TrendSource | None,
    limit: int,
    offset: int,
) -> list[TrendRead]:
    # LEFT JOIN scoped to the caller's workspace so "consumed" reflects only
    # this workspace's read-state, never another workspace's.
    stmt = (
        select(Trend, TrendConsumption.consumed_at)
        .outerjoin(
            TrendConsumption,
            and_(
                TrendConsumption.trend_id == Trend.id,
                TrendConsumption.workspace_id == workspace_id,
            ),
        )
        .order_by(Trend.fetched_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status == "unconsumed":
        stmt = stmt.where(TrendConsumption.consumed_at.is_(None))
    elif status == "consumed":
        stmt = stmt.where(TrendConsumption.consumed_at.is_not(None))
    if source is not None:
        stmt = stmt.where(Trend.source == source)
    result = await session.execute(stmt)
    return [_row_to_read(trend, consumed_at) for trend, consumed_at in result.all()]


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(_: User = Depends(get_current_user)) -> RefreshResponse:
    summary = await run_retrieval()
    return RefreshResponse(**summary)


@router.get("", response_model=list[TrendRead])
async def list_trends(
    status: Literal["unconsumed", "consumed", "all"] = Query("unconsumed"),
    source: TrendSource | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, description="Skip N rows — drives 'Load more'."),
    workspace_id: UUID = Depends(get_current_workspace),
    session: AsyncSession = Depends(get_session),
) -> list[TrendRead]:
    return await _query_trends(session, workspace_id, status, source, limit, offset)


class TrendStats(BaseModel):
    """Unconsumed (per-workspace) / total (shared-pool size) counts for the
    Inbox badge + Today's counter."""

    unconsumed: int = 0
    total: int = 0


@router.get("/stats", response_model=TrendStats)
async def trend_stats(
    workspace_id: UUID = Depends(get_current_workspace),
    session: AsyncSession = Depends(get_session),
) -> TrendStats:
    total = (
        await session.execute(select(func.count()).select_from(Trend))
    ).scalar_one()
    unconsumed = (
        await session.execute(
            select(func.count())
            .select_from(Trend)
            .outerjoin(
                TrendConsumption,
                and_(
                    TrendConsumption.trend_id == Trend.id,
                    TrendConsumption.workspace_id == workspace_id,
                ),
            )
            .where(TrendConsumption.consumed_at.is_(None))
        )
    ).scalar_one()
    return TrendStats(unconsumed=unconsumed, total=total)


async def _set_consumed(
    session: AsyncSession, trend_id: UUID, workspace_id: UUID, consumed: bool
) -> datetime | None:
    if consumed:
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(TrendConsumption)
            .values(trend_id=trend_id, workspace_id=workspace_id, consumed_at=now)
            .on_conflict_do_update(
                index_elements=[TrendConsumption.trend_id, TrendConsumption.workspace_id],
                set_={"consumed_at": now},
            )
        )
        await session.execute(stmt)
        return now
    await session.execute(
        delete(TrendConsumption).where(
            TrendConsumption.trend_id == trend_id,
            TrendConsumption.workspace_id == workspace_id,
        )
    )
    return None


@router.patch("/{trend_id}", response_model=TrendRead)
async def update_trend(
    trend_id: UUID,
    patch: TrendPatch,
    workspace_id: UUID = Depends(get_current_workspace),
    session: AsyncSession = Depends(get_session),
) -> TrendRead:
    trend = await session.get(Trend, trend_id)
    if trend is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="trend not found"
        )
    consumed_at = await _set_consumed(session, trend_id, workspace_id, patch.consumed)
    await session.commit()
    return _row_to_read(trend, consumed_at)


@router.delete("/{trend_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_trend(
    trend_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
) -> Response:
    """Hard delete — removes the row from the shared pool for every
    workspace. Admin-only (2026-08-16): trends aren't private, so this has
    cross-workspace effect. Everyday cleanup is `dismiss-all` (per-workspace,
    non-destructive) or the automatic retention sweep."""
    trend = await session.get(Trend, trend_id)
    if trend is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="trend not found"
        )
    await session.delete(trend)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/dismiss-all", response_model=DismissAllResponse)
async def dismiss_all_trends(
    status_filter: Literal["unconsumed", "consumed", "all"] = Query(
        "unconsumed", alias="status"
    ),
    source: TrendSource | None = Query(None),
    refill: int = Query(0, ge=0, le=200, description="Rows of the active filter to return post-dismiss."),
    workspace_id: UUID = Depends(get_current_workspace),
    session: AsyncSession = Depends(get_session),
) -> DismissAllResponse:
    """Mark every trend matching the filter as consumed for the caller's
    workspace — one call, no id list, no pagination. Non-destructive: this
    never touches the shared `Trend` row, only this workspace's read-state,
    so it can't affect any other workspace."""
    ids_stmt = select(Trend.id)
    if source is not None:
        ids_stmt = ids_stmt.where(Trend.source == source)
    if status_filter != "all":
        ids_stmt = ids_stmt.outerjoin(
            TrendConsumption,
            and_(
                TrendConsumption.trend_id == Trend.id,
                TrendConsumption.workspace_id == workspace_id,
            ),
        )
        if status_filter == "unconsumed":
            ids_stmt = ids_stmt.where(TrendConsumption.consumed_at.is_(None))
        else:
            ids_stmt = ids_stmt.where(TrendConsumption.consumed_at.is_not(None))
    ids = list((await session.execute(ids_stmt)).scalars().all())

    dismissed = 0
    if ids:
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(TrendConsumption)
            .values([{"trend_id": tid, "workspace_id": workspace_id, "consumed_at": now} for tid in ids])
            .on_conflict_do_update(
                index_elements=[TrendConsumption.trend_id, TrendConsumption.workspace_id],
                set_={"consumed_at": now},
            )
        )
        result = await session.execute(stmt)
        dismissed = result.rowcount or len(ids)
        await session.commit()

    next_page = (
        await _query_trends(session, workspace_id, "unconsumed", source, refill, 0)
        if refill
        else []
    )
    return DismissAllResponse(dismissed=dismissed, next=next_page)
