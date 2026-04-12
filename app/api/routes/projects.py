from __future__ import annotations

"""Project API routes for the Lovable frontend."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.api.deps import get_current_user
from app.models.user import User
from app.models.project import Project

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectResponse(BaseModel):
    id: int
    name: str
    color: str | None

    model_config = {"from_attributes": True}


@router.get("")
async def list_projects(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = await session.execute(select(Project).order_by(Project.id))
    projects = result.scalars().all()
    return [{"id": p.id, "name": p.name, "color": p.color} for p in projects]
