"""Prompts API — read the versioned prompt matrix and activate a version.

Makes "voice tuning = a DB write, not a deploy" usable from the dashboard
(DESIGN.md §5G). The generator looks a prompt up by (name, platform, is_active);
activating a version flips `is_active` within its (name, platform) group so the
matrix never has two live rows for the same key. Read + activate only — authoring
new prompt bodies stays a migration concern (anchor examples are how voice quality
is controlled; a free-form editor risks generic output).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db import get_session
from app.models import User
from app.models.base import Platform, PostCategory
from app.models.prompt import Prompt

router = APIRouter(prefix="/prompts", tags=["prompts"])


class PromptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    category: PostCategory
    platform: Platform | None
    body: str
    version: int
    is_active: bool


@router.get("", response_model=list[PromptRead])
async def list_prompts(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list[PromptRead]:
    """Every prompt row, newest version first within each (name, platform) group."""
    rows = (
        (
            await session.execute(
                select(Prompt).order_by(
                    Prompt.name,
                    Prompt.platform,
                    Prompt.version.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return [PromptRead.model_validate(r) for r in rows]


@router.post("/{prompt_id}/activate", response_model=PromptRead)
async def activate_prompt(
    prompt_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PromptRead:
    """Make this version the live one for its (name, platform) key.

    Deactivates every sibling first so the generator's `is_active` lookup
    resolves to exactly one row. NULL platform (the legacy/any variant) is its
    own group — Postgres treats NULLs as distinct, so we match it with IS NULL.
    """
    prompt = await session.get(Prompt, prompt_id)
    if prompt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="prompt not found"
        )

    sibling_filter = (
        Prompt.platform.is_(None)
        if prompt.platform is None
        else Prompt.platform == prompt.platform
    )
    await session.execute(
        update(Prompt)
        .where(Prompt.name == prompt.name, sibling_filter)
        .values(is_active=False)
    )
    prompt.is_active = True
    await session.commit()
    await session.refresh(prompt)
    return PromptRead.model_validate(prompt)
