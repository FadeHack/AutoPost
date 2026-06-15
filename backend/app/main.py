from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.config import settings
from app.core.logging import configure_logging, get_logger

configure_logging()
log = get_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.rendering import playwright_runner
    from app.scheduler.scheduler import shutdown_scheduler, start_scheduler

    log.info("app.starting", env_base_url=settings.APP_BASE_URL)
    scheduler = start_scheduler()
    log.info(
        "scheduler.started",
        jobs=[j.id for j in scheduler.get_jobs()],
        timezone=settings.TIMEZONE,
    )
    await playwright_runner.start()
    try:
        yield
    finally:
        log.info("app.stopping")
        await playwright_runner.stop()
        shutdown_scheduler()


app = FastAPI(
    title="AutoPost API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_BASE_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "AutoPost API", "version": app.version, "docs": "/docs"}
