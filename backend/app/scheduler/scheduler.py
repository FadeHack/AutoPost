"""APScheduler singleton + lifecycle.

AsyncIOScheduler binds to the FastAPI event loop when start() is called
inside the lifespan hook. Jobs persist across restarts via
SQLAlchemyJobStore (which is sync and uses a separate psycopg connection
to the same Postgres DB).
"""
from __future__ import annotations

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings

_scheduler: AsyncIOScheduler | None = None


def _sync_url(url: str) -> str:
    """APScheduler's SQLAlchemyJobStore is sync — coerce any URL form
    (plain or asyncpg) to psycopg sync."""
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            jobstores={
                "default": SQLAlchemyJobStore(
                    url=_sync_url(settings.DATABASE_URL)
                )
            },
            timezone=settings.TIMEZONE,
        )
    return _scheduler


def start_scheduler() -> AsyncIOScheduler:
    s = get_scheduler()
    if not s.running:
        # Imported late to avoid circular imports during app startup.
        from app.scheduler.jobs import register_recurring_jobs

        register_recurring_jobs(s)
        s.start()
    return s


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
