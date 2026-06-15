"""Templates API — list visual templates so the dashboard can offer a picker."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db import get_session
from app.models import User
from app.models.base import TemplateCategory
from app.models.template import Template

router = APIRouter(prefix="/templates", tags=["templates"])


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    category: TemplateCategory
    html_path: str
    thumbnail_url: str | None


@router.get("", response_model=list[TemplateRead])
async def list_templates(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list[TemplateRead]:
    rows = (
        (await session.execute(select(Template).order_by(Template.name)))
        .scalars()
        .all()
    )
    return [TemplateRead.model_validate(r) for r in rows]
