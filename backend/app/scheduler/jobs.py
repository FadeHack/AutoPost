"""Recurring jobs registered on scheduler start.

Add new jobs by writing a coroutine here and appending another add_job()
call in register_recurring_jobs(). Job IDs are stable strings so
replace_existing=True works idempotently across restarts.
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


async def cleanup_consumed_trends_job() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.TRENDS_CONSUMED_RETENTION_DAYS
    )
    log.info("scheduler.trends_cleanup.fire", cutoff=cutoff.isoformat())
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                delete(Trend).where(
                    Trend.consumed_at.is_not(None),
                    Trend.consumed_at < cutoff,
                )
            )
            await session.commit()
        log.info(
            "scheduler.trends_cleanup.complete",
            deleted=result.rowcount or 0,
        )
    except Exception as e:
        log.exception("scheduler.trends_cleanup.failed", error=str(e))


async def retrieval_job() -> None:
    log.info("scheduler.retrieval.fire")
    try:
        summary = await run_retrieval()
        log.info("scheduler.retrieval.complete", **summary)
    except Exception as e:
        log.exception("scheduler.retrieval.failed", error=str(e))


def publish_job_id(post_id: UUID | str) -> str:
    """Stable per-post job id so reschedule/cancel can target the same job
    via `replace_existing=True` / `remove_job(id)`."""
    return f"publish:{post_id}"


async def publish_post_job(post_id: str) -> None:
    """APScheduler one-shot: open a fresh DB session and publish.

    Job args must be JSON-serializable for SQLAlchemyJobStore, so the post_id
    is stored as a string and converted to UUID inside the job.
    """
    from app.publishing.publisher import publish_post  # late import — avoids
    # pulling publisher (and its httpx/supabase imports) into scheduler startup.

    log.info("scheduler.publish.fire", post_id=post_id)
    pid = UUID(post_id)
    try:
        async with AsyncSessionLocal() as session:
            post = await publish_post(session, pid)
        log.info(
            "scheduler.publish.complete",
            post_id=post_id,
            status=post.status.value,
            urn=post.linkedin_urn,
        )
    except Exception as e:
        # Publisher already wrote status=failed and a PublishingLog row for
        # any LinkedIn-API error. This catches the rare pre-flight bug
        # (DB unreachable, etc.) that escaped publish_post itself.
        log.exception("scheduler.publish.crashed", post_id=post_id, error=str(e))


def schedule_publish(
    scheduler: AsyncIOScheduler, post_id: UUID, run_date,
) -> None:
    """Register or replace a one-shot publish job for `post_id` at `run_date`."""
    scheduler.add_job(
        publish_post_job,
        trigger=DateTrigger(run_date=run_date),
        args=[str(post_id)],
        id=publish_job_id(post_id),
        replace_existing=True,
        # A scheduler restart could miss the exact fire time; allow a 1h grace
        # so a published-while-offline post still goes out when the worker comes back.
        misfire_grace_time=3600,
        coalesce=True,
    )


def cancel_publish(scheduler: AsyncIOScheduler, post_id: UUID) -> bool:
    """Remove any pending publish job for the post. Returns True if one existed."""
    jid = publish_job_id(post_id)
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
        cleanup_consumed_trends_job,
        trigger=CronTrigger.from_crontab(
            settings.TRENDS_CLEANUP_CRON, timezone=settings.TIMEZONE
        ),
        id=TRENDS_CLEANUP_JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )
