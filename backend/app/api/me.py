"""Current-user endpoint — lets the frontend gate on identity + role (e.g. show the
/admin nav entry only to admins) and know which workspace it's operating in."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.core.auth import get_current_user
from app.models import User
from app.models.base import UserRole

router = APIRouter(prefix="/me", tags=["me"])


class MeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: UserRole
    workspace_id: UUID


@router.get("", response_model=MeRead)
async def read_me(user: User = Depends(get_current_user)) -> MeRead:
    return MeRead.model_validate(user)
