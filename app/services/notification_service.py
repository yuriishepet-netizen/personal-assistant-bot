"""Notification service — sends Telegram push notifications for task events."""

import logging

from aiogram import Bot

from app.models.task import Task
from app.models.user import User

logger = logging.getLogger(__name__)


async def notify_task_assigned(bot: Bot, task: Task, assignee: User, assigner: User) -> None:
    """Notify a user that a task has been assigned to them."""
    priority_emoji = {
        "low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴",
    }.get(task.priority.value if hasattr(task.priority, "value") else task.priority, "⚪")

    deadline_str = f"\n📅 Дедлайн: {task.deadline.strftime('%d.%m.%Y %H:%M')}" if task.deadline else ""

    message = (
        f"📌 <b>Тебе назначена задача</b>\n\n"
        f"{priority_emoji} <b>#{task.id} {task.title}</b>\n"
        f"👤 От: {assigner.name}"
        f"{deadline_str}"
    )

    try:
        await bot.send_message(
            chat_id=assignee.telegram_id,
            text=message,
            parse_mode="HTML",
        )
        logger.info("Sent assignment notification for task #%s to user %s", task.id, assignee.name)
    except Exception as e:
        logger.error("Failed to send assignment notification for task #%s: %s", task.id, e)


async def notify_task_created(bot: Bot, task: Task, creator: User, team_users: list[User]) -> None:
    """Notify all team members (except the creator) that a new task was created."""
    priority_emoji = {
        "low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴",
    }.get(task.priority.value if hasattr(task.priority, "value") else task.priority, "⚪")

    deadline_str = f"\n📅 Дедлайн: {task.deadline.strftime('%d.%m.%Y %H:%M')}" if task.deadline else ""

    message = (
        f"🆕 <b>Новая задача</b>\n\n"
        f"{priority_emoji} <b>#{task.id} {task.title}</b>\n"
        f"👤 Создал: {creator.name}"
        f"{deadline_str}"
    )

    for user in team_users:
        if user.id == creator.id:
            continue  # Don't notify the creator
        try:
            await bot.send_message(
                chat_id=user.telegram_id,
                text=message,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("Failed to send task creation notification to user %s: %s", user.name, e)


async def notify_overdue_to_admins(bot: Bot, task: Task, admin_users: list[User]) -> None:
    """Notify admin users about an overdue task."""
    assignee_name = task.assignee.name if task.assignee else "не назначен"

    message = (
        f"🚨 <b>Просроченная задача!</b>\n\n"
        f"<b>#{task.id} {task.title}</b>\n"
        f"📅 Дедлайн: {task.deadline.strftime('%d.%m.%Y %H:%M')}\n"
        f"👤 Ответственный: {assignee_name}\n"
        f"📊 Статус: {task.status.value}"
    )

    for admin in admin_users:
        try:
            await bot.send_message(
                chat_id=admin.telegram_id,
                text=message,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("Failed to send overdue notification to admin %s: %s", admin.name, e)
