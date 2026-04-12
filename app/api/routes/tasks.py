from __future__ import annotations

"""Task API routes for the Lovable frontend."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.api.deps import get_current_user
from app.models.user import User
from app.models.task import TaskStatus, TaskPriority
from app.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    status: TaskStatus = TaskStatus.BACKLOG
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_id: int | None = None
    deadline: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assignee_id: int | None = None
    deadline: datetime | None = None


class CommentCreate(BaseModel):
    text: str


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str | None
    status: str
    priority: str
    assignee_id: int | None
    assignee_name: str | None = None
    creator_id: int
    creator_name: str | None = None
    deadline: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CommentResponse(BaseModel):
    id: int
    task_id: int
    user_id: int
    user_name: str | None = None
    text: str
    created_at: datetime

    model_config = {"from_attributes": True}


def _task_to_response(task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "assignee_id": task.assignee_id,
        "assignee_name": task.assignee.name if task.assignee else None,
        "creator_id": task.creator_id,
        "creator_name": task.creator.name if task.creator else None,
        "deadline": task.deadline,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


@router.get("")
async def list_tasks(
    status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    assignee_id: int | None = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    tasks = await task_service.get_tasks(session, status=status, assignee_id=assignee_id, priority=priority, limit=limit, offset=offset)
    return [_task_to_response(t) for t in tasks]


@router.post("", status_code=201)
async def create_task_endpoint(
    body: TaskCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    task = await task_service.create_task(
        session=session,
        title=body.title,
        creator_id=current_user.id,
        description=body.description,
        status=body.status,
        priority=body.priority,
        assignee_id=body.assignee_id,
        deadline=body.deadline,
    )
    return _task_to_response(task)


@router.get("/{task_id}")
async def get_task_endpoint(
    task_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    task = await task_service.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_to_response(task)


@router.patch("/{task_id}")
async def update_task_endpoint(
    task_id: int,
    body: TaskUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    task = await task_service.update_task(session, task_id, **updates)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_to_response(task)


@router.delete("/{task_id}", status_code=200)
async def delete_task_endpoint(
    task_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    deleted = await task_service.delete_task(session, task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "ok", "message": f"Task #{task_id} deleted"}


@router.get("/{task_id}/comments")
async def list_comments(
    task_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    task = await task_service.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return [
        {
            "id": c.id,
            "task_id": c.task_id,
            "user_id": c.user_id,
            "user_name": c.user.name if c.user else None,
            "text": c.text,
            "created_at": c.created_at,
        }
        for c in task.comments
    ]


@router.post("/{task_id}/comments", status_code=201)
async def add_comment_endpoint(
    task_id: int,
    body: CommentCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    comment = await task_service.add_comment(session, task_id, current_user.id, body.text)
    return {"id": comment.id, "task_id": comment.task_id, "text": comment.text, "created_at": comment.created_at}
