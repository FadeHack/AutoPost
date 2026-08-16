"""Recurring jobs registered on scheduler start.

Add new jobs by writing a coroutine here and appending another add_job()
call in register_recurring_jobs(). Job IDs are stable strings so
replace_existing=True works idempotently across restarts.

Phase 11 (Chunk A): publish jobs are per-PostTarget, not per-Post. A draft
scheduled for both LinkedIn + Bluesky becomes two independent APScheduler
one-shots so different platform rate limits / failure modes stay isolated.
"""
from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from datetime import datetime, timedelta, timezone
from uuid import UUID

from apscheduler.triggers.date import DateTrigger
from sqlalchemy import delete

from app.config import settings
from app.db import AsyncSessionLocal
from app.models import Trend
from app.retrieval.orchestrator import run_retrieval

log = structlog.get_logger()

RETRIEVAL_JOB_ID = "retrieval"
TRENDS_CLEANUP_JOB_ID = "trends_cleanup"


async def trend_retention_job() -> None:
    """Daily sweep of the shared trend pool (2026-08-16, user-confirmed 7-day
    window). Purely time-based on `fetched_at` — NOT gated on consumption,
    because consumption is per-workspace (`TrendConsumption`) as of this same
    change, so there's no single "is this trend done" flag to check anymore.
    A trend past the retention window leaves the pool for every workspace
    regardless of who has or hasn't acted on it; `TrendConsumption` rows
    cascade-delete with it. Safe: nothing dereferences trend content once a
    draft exists (`Post.source_trend_ids` only ever renders as a count)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.TREND_RETENTION_DAYS)
    log.info("scheduler.trend_retention.fire", cutoff=cutoff.isoformat())
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                delete(Trend).where(Trend.fetched_at < cutoff)
            )
            await session.commit()
        log.info(
            "scheduler.trend_retention.complete",
            deleted=result.rowcount or 0,
        )
    except Exception as e:
        log.exception("scheduler.trend_retention.failed", error=str(e))


async def retrieval_job() -> None:
    log.info("scheduler.retrieval.fire")
    try:
        summary = await run_retrieval()
        log.info("scheduler.retrieval.complete", **summary)
    except Exception as e:
        log.exception("scheduler.retrieval.failed", error=str(e))


def publish_target_job_id(target_id: UUID | str) -> str:
    """Stable per-target job id so reschedule/cancel can target the same job
    via `replace_existing=True` / `remove_job(id)`."""
    return f"publish-target:{target_id}"


async def publish_target_job(target_id: str) -> None:
    """APScheduler one-shot: open a fresh DB session and publish ONE target.

    Job args must be JSON-serializable for SQLAlchemyJobStore, so the
    target_id is stored as a string and converted to UUID inside the job.
    """
    from app.publishing.orchestrator import publish_target  # late import

    log.info("scheduler.publish_target.fire", target_id=target_id)
    tid = UUID(target_id)
    try:
        async with AsyncSessionLocal() as session:
            target = await publish_target(session, tid)
        log.info(
            "scheduler.publish_target.complete",
            target_id=target_id,
            platform=target.platform.value,
            status=target.status.value,
            urn=target.external_urn,
        )
    except Exception as e:
        # Orchestrator already wrote status=failed and a PublishingLog row
        # for any platform error. This catches the rare pre-flight bug
        # (DB unreachable, etc.) that escaped publish_target itself.
        log.exception(
            "scheduler.publish_target.crashed", target_id=target_id, error=str(e)
        )


def schedule_target_publish(
    scheduler: AsyncIOScheduler, target_id: UUID, run_date,
) -> None:
    """Register or replace a one-shot publish job for `target_id` at `run_date`."""
    scheduler.add_job(
        publish_target_job,
        trigger=DateTrigger(run_date=run_date),
        args=[str(target_id)],
        id=publish_target_job_id(target_id),
        replace_existing=True,
        # Scheduler restart could miss the exact fire time; allow a 1h grace
        # so a published-while-offline target still goes out when the worker
        # comes back.
        misfire_grace_time=3600,
        coalesce=True,
    )


def cancel_target_publish(scheduler: AsyncIOScheduler, target_id: UUID) -> bool:
    """Remove any pending publish job for the target. Returns True if one existed."""
    jid = publish_target_job_id(target_id)
    if scheduler.get_job(jid) is None:
        return False
    scheduler.remove_job(jid)
    return True


def register_recurring_jobs(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(
        retrieval_job,
        trigger=CronTrigger.from_crontab(
            settings.RETRIEVAL_CRON, timezone=settings.TIMEZONE
        ),
        id=RETRIEVAL_JOB_ID,
        replace_existing=True,
        misfire_grace_time=600,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        trend_retention_job,
        trigger=CronTrigger.from_crontab(
            settings.TRENDS_CLEANUP_CRON, timezone=settings.TIMEZONE
        ),
        id=TRENDS_CLEANUP_JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )
