"""Top-level API router. Sub-routers are mounted here so `app/main.py` only includes one."""

from fastapi import APIRouter

from app.api import (
    auth_bluesky,
    auth_instagram,
    auth_linkedin,
    auth_mastodon,
    auth_threads,
    posts,
    templates,
    trends,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_linkedin.router)
api_router.include_router(auth_bluesky.router)
api_router.include_router(auth_mastodon.router)
api_router.include_router(auth_threads.router)
api_router.include_router(auth_instagram.router)
api_router.include_router(trends.router)
api_router.include_router(posts.router)
api_router.include_router(templates.router)

__all__ = ["api_router"]
