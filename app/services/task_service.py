from __future__ import annotations

"""Task and User CRUD operations."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.task import Task, TaskStatus, TaskPriority
from app.models.comment import Comment
from app.models.attachment import Attachment
from app.models.project import Project  # noqa: F401


async def create_task(
    session: AsyncSession,
    title: str,
    creator_id: int,
    description: str | None = None,
    status: TaskStatus = TaskStatus.BACKLOG,
    priority: TaskPriority = TaskPriority.MEDIUM,
    assignee_id: int | None = None,
    deadline: datetime | None = None,
    calendar_event_id: str | None = None,
    project_id: int | None = None,
) -> Task:
    task = Task(
        title=title,
        description=description,
        status=status,
        priority=priority,
        creator_id=creator_id,
        assignee_id=assignee_id,
        deadline=deadline,
        calendar_event_id=calendar_event_id,
        project_id=project_id,
    )
    session.add(task)
    await session.commit()
    # Re-fetch with relationships loaded to avoid lazy-load in async
    return await get_task(session, task.id)


async def get_task(session: AsyncSession, task_id: int) -> Task | None:
    result = await session.execute(
        select(Task)
        .options(
            selectinload(Task.assignee),
            selectinload(Task.creator),
            selectinload(Task.comments).selectinload(Comment.user),
            selectinload(Task.attachments),
            selectinload(Task.project),
        )
        .where(Task.id == task_id)
    )
    return result.scalar_one_or_none()


async def get_tasks(
    session: AsyncSession,
    status: TaskStatus | None = None,
    assignee_id: int | None = None,
    priority: TaskPriority | None = None,
    project_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Task]:
    query = select(Task).options(
        selectinload(Task.assignee),
        selectinload(Task.creator),
        selectinload(Task.project),
    )

    if status:
        query = query.where(Task.status == status)
    if assignee_id:
        query = query.where(Task.assignee_id == assignee_id)
    if priority:
        query = query.where(Task.priority == priority)
    if project_id:
        query = query.where(Task.project_id == project_id)

    query = query.order_by(Task.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(query)
    return list(result.scalars().all())


async def update_task(session: AsyncSession, task_id: int, **kwargs) -> Task | None:
    await session.execute(update(Task).where(Task.id == task_id).values(**kwargs))
    await session.commit()
    return await get_task(session, task_id)


async def delete_task(session: AsyncSession, task_id: int) -> bool:
    """Delete a task and its related comments/attachments. Returns True if deleted."""
    task = await get_task(session, task_id)
    if not task:
        return False
    await session.delete(task)
    await session.commit()
    return True


async def add_comment(session: AsyncSession, task_id: int, user_id: int, text: str) -> Comment:
    comment = Comment(task_id=task_id, user_id=user_id, text=text)
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    return comment


async def add_attachment(
    session: AsyncSession, task_id: int, file_type: str, file_url: str, original_name: str | None = None
) -> Attachment:
    attachment = Attachment(
        task_id=task_id,
        file_type=file_type,
        file_url=file_url,
        original_name=original_name,
    )
    session.add(attachment)
    await session.commit()
    await session.refresh(attachment)
    return attachment


async def get_tasks_with_upcoming_deadlines(session: AsyncSession, before: datetime) -> list[Task]:
    """Get tasks with deadlines before the given datetime that are not done."""
    result = await session.execute(
        select(Task)
        .options(selectinload(Task.assignee))
        .where(
            Task.deadline.isnot(None),
            Task.deadline <= before,
            Task.status != TaskStatus.DONE,
        )
        .order_by(Task.deadline)
    )
    return list(result.scalars().all())
