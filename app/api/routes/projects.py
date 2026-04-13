from __future__ import annotations

"""Project API routes for the Lovable frontend."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.api.deps import get_current_user
from app.models.user import User
from app.models.project import Project, project_members

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
    # Only show public projects + private projects the user is a member of
    accessible_private = (
        select(project_members.c.project_id)
        .where(project_members.c.user_id == current_user.id)
    )
    query = (
        select(Project)
        .where(
            or_(
                Project.is_private == False,  # noqa: E712
                Project.id.in_(accessible_private),
            )
        )
        .order_by(Project.id)
    )
    result = await session.execute(query)
    projects = result.scalars().all()
    return [{"id": p.id, "name": p.name, "color": p.color} for p in projects]
