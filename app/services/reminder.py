"""Reminder service — checks for upcoming deadlines and sends Telegram notifications."""

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import async_session
from app.models.task import Task, TaskStatus
from app.models.user import User, UserRole
from app.services import notification_service
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Track sent reminders to avoid duplicates: set of (task_id, reminder_type)
_sent_reminders: set[tuple[int, str]] = set()


async def check_and_send_reminders(bot: Bot) -> None:
    """Check for tasks with upcoming deadlines and send reminders."""
    now = datetime.now().astimezone()

    async with async_session() as session:
        # Fetch all non-done tasks that have deadlines
        result = await session.execute(
            select(Task)
            .options(selectinload(Task.assignee))
            .where(
                Task.deadline.isnot(None),
                Task.status != TaskStatus.DONE,
            )
            .order_by(Task.deadline)
        )
        tasks = list(result.scalars().all())

        # Fetch admin users for overdue notifications
        admin_result = await session.execute(
            select(User).where(User.role == UserRole.ADMIN)
        )
        admin_users = list(admin_result.scalars().all())

        for task in tasks:
            if not task.deadline:
                continue

            time_left = task.deadline - now
            total_seconds = time_left.total_seconds()

            # --- Overdue tasks: notify admins ---
            if total_seconds < 0:
                reminder_key = (task.id, "overdue")
                # Send overdue once, then re-send every 6 hours
                hours_overdue = abs(total_seconds) / 3600
                overdue_cycle = int(hours_overdue / 6)
                reminder_key = (task.id, f"overdue_{overdue_cycle}")
                if reminder_key not in _sent_reminders:
                    await notification_service.notify_overdue_to_admins(bot, task, admin_users)
                    # Also notify assignee
                    if task.assignee:
                        await _send_reminder(bot, task, "ПРОСРОЧЕНА ⚠️", task.id, "overdue_assignee")
                    _sent_reminders.add(reminder_key)
                continue

            # --- At deadline (within 5 min window) ---
            if total_seconds <= 300:  # 5 minutes
                reminder_key = (task.id, "now")
                if reminder_key not in _sent_reminders:
                    await _send_reminder(bot, task, "СЕЙЧАС!", task.id, "now")
                    _sent_reminders.add(reminder_key)

            # --- 1 hour before (between 55-65 min) ---
            elif 3300 <= total_seconds <= 3900:
                reminder_key = (task.id, "1h")
                if reminder_key not in _sent_reminders:
                    minutes = int(total_seconds / 60)
                    await _send_reminder(bot, task, f"через {minutes} мин", task.id, "1h")
                    _sent_reminders.add(reminder_key)

            # --- 1 day before (between 23-25 hours) ---
            elif 82800 <= total_seconds <= 90000:
                reminder_key = (task.id, "1d")
                if reminder_key not in _sent_reminders:
                    hours = int(total_seconds / 3600)
                    await _send_reminder(bot, task, f"через {hours} ч", task.id, "1d")
                    _sent_reminders.add(reminder_key)

    # Cleanup old entries (remove reminders for tasks older than 7 days)
    _cleanup_sent_reminders()


async def _send_reminder(bot: Bot, task: Task, time_str: str, task_id: int, reminder_type: str) -> None:
    """Send a deadline reminder to the task assignee."""
    if not task.assignee:
        return

    priority_emoji = {
        "low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴",
    }.get(task.priority.value, "⚪")

    if "ПРОСРОЧЕНА" in time_str:
        header = "🚨 <b>Задача просрочена!</b>"
    elif time_str == "СЕЙЧАС!":
        header = "⏰ <b>Дедлайн наступил!</b>"
    else:
        header = "⏰ <b>Напоминание о дедлайне</b>"

    message = (
        f"{header}\n\n"
        f"{priority_emoji} <b>{task.title}</b>\n"
        f"📅 Дедлайн: {task.deadline.strftime('%d.%m.%Y %H:%M')} ({time_str})\n"
        f"📊 Статус: {task.status.value}"
    )

    try:
        await bot.send_message(
            chat_id=task.assignee.telegram_id,
            text=message,
            parse_mode="HTML",
        )
        logger.info("Sent %s reminder for task #%s to %s", reminder_type, task_id, task.assignee.name)
    except Exception as e:
        logger.error("Failed to send reminder for task %s: %s", task_id, e)


def _cleanup_sent_reminders() -> None:
    """Keep the sent_reminders set from growing indefinitely."""
    if len(_sent_reminders) > 1000:
        _sent_reminders.clear()
        logger.info("Cleared sent_reminders cache")


async def reminder_loop(bot: Bot, check_interval_seconds: int = 300) -> None:
    """Run reminder checks in a loop (every 5 minutes)."""
    while True:
        try:
            await check_and_send_reminders(bot)
        except Exception as e:
            logger.error("Reminder loop error: %s", e)
        await asyncio.sleep(check_interval_seconds)
