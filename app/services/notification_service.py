"""Notification service — sends Telegram push notifications for task events."""

import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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


def _review_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Inline keyboard for review notification: Accept / Rework."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять задачу", callback_data=f"review_accept:{task_id}"),
            InlineKeyboardButton(text="🔄 Доработать", callback_data=f"review_rework:{task_id}"),
        ],
    ])


async def notify_task_review(bot: Bot, task: Task, admin_users: list[User]) -> None:
    """Notify admin(s) that a task has been moved to 'review' status.

    Shows inline buttons: Accept (→ done) and Rework (→ send feedback).
    """
    assignee_name = task.assignee.name if task.assignee else "не назначен"
    project_name = task.project.name if hasattr(task, "project") and task.project else None
    deadline_str = f"\n📅 Дедлайн: {task.deadline.strftime('%d.%m.%Y %H:%M')}" if task.deadline else ""
    project_str = f"\n📁 Проект: {project_name}" if project_name else ""

    message = (
        f"👀 <b>Задача на проверке</b>\n\n"
        f"<b>#{task.id} {task.title}</b>\n"
        f"👤 Ответственный: {assignee_name}"
        f"{deadline_str}"
        f"{project_str}"
    )

    kb = _review_keyboard(task.id)

    for admin in admin_users:
        try:
            await bot.send_message(
                chat_id=admin.telegram_id,
                text=message,
                reply_markup=kb,
                parse_mode="HTML",
            )
            logger.info("Sent review notification for task #%s to admin %s", task.id, admin.name)
        except Exception as e:
            logger.error("Failed to send review notification to admin %s: %s", admin.name, e)


async def notify_rework(bot: Bot, task: Task, assignee: User, feedback: str, reviewer: User) -> None:
    """Notify the assignee that their task needs rework, with feedback."""
    message = (
        f"🔄 <b>Задача требует доработки</b>\n\n"
        f"<b>#{task.id} {task.title}</b>\n\n"
        f"💬 Комментарий от {reviewer.name}:\n"
        f"<i>{feedback}</i>"
    )

    try:
        await bot.send_message(
            chat_id=assignee.telegram_id,
            text=message,
            parse_mode="HTML",
        )
        logger.info("Sent rework notification for task #%s to %s", task.id, assignee.name)
    except Exception as e:
        logger.error("Failed to send rework notification for task #%s: %s", task.id, e)


async def notify_task_accepted(bot: Bot, task: Task, assignee: User, reviewer: User) -> None:
    """Notify the assignee that their task has been accepted."""
    message = (
        f"✅ <b>Задача принята!</b>\n\n"
        f"<b>#{task.id} {task.title}</b>\n"
        f"👤 Принял: {reviewer.name}"
    )

    try:
        await bot.send_message(
            chat_id=assignee.telegram_id,
            text=message,
            parse_mode="HTML",
        )
        logger.info("Sent acceptance notification for task #%s to %s", task.id, assignee.name)
    except Exception as e:
        logger.error("Failed to send acceptance notification for task #%s: %s", task.id, e)


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
