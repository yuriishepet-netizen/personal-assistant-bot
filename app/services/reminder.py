"""Reminder service — checks for upcoming deadlines and sends Telegram notifications."""

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot

from app.db.session import async_session
from app.services.task_service import get_tasks_with_upcoming_deadlines
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

REMINDER_INTERVALS = [
    timedelta(hours=1),
    timedelta(days=1),
]


async def check_and_send_reminders(bot: Bot) -> None:
    """Check for tasks with upcoming deadlines and send reminders."""
    now = datetime.now().astimezone()

    async with async_session() as session:
        for interval in REMINDER_INTERVALS:
            deadline_threshold = now + interval
            tasks = await get_tasks_with_upcoming_deadlines(session, before=deadline_threshold)

            for task in tasks:
                if not task.assignee or not task.deadline:
                    continue

                time_left = task.deadline - now
                if time_left.total_seconds() <= 0:
                    time_str = "ПРОСРОЧЕНА"
                elif time_left < timedelta(hours=2):
                    minutes = int(time_left.total_seconds() / 60)
                    time_str = f"через {minutes} мин"
                elif time_left < timedelta(days=1):
                    hours = int(time_left.total_seconds() / 3600)
                    time_str = f"через {hours} ч"
                else:
                    days = time_left.days
                    time_str = f"через {days} дн"

                priority_emoji = {
                    "low": "🟢",
                    "medium": "🟡",
                    "high": "🟠",
                    "critical": "🔴",
                }.get(task.priority, "⚪")

                message = (
                    f"⏰ <b>Напоминание о дедлайне</b>\n\n"
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
                except Exception as e:
                    logger.error(f"Failed to send reminder for task {task.id}: {e}")


async def reminder_loop(bot: Bot, check_interval_seconds: int = 1800) -> None:
    """Run reminder checks in a loop."""
    while True:
        try:
            await check_and_send_reminders(bot)
        except Exception as e:
            logger.error(f"Reminder loop error: {e}")
        await asyncio.sleep(check_interval_seconds)
