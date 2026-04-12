"""Calendar handlers — create meetings, view events, Google OAuth."""

import logging
import uuid
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services import calendar as cal_service
from app.services import ai_parser, user_service
from app.bot.keyboards import meeting_confirm_keyboard

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("connect_google"))
async def cmd_connect_google(message: Message, db_user: User):
    """Send Google OAuth link."""
    try:
        auth_url = cal_service.get_auth_url(state=str(db_user.telegram_id))
        await message.answer(
            f"🔗 Подключи Google Calendar:\n\n{auth_url}\n\n"
            "После авторизации ты будешь перенаправлен обратно.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Google auth error: {e}")
        await message.answer("❌ Ошибка. Проверь настройки Google OAuth.")


@router.message(Command("calendar"))
async def cmd_calendar(message: Message, session: AsyncSession, db_user: User):
    """Show upcoming calendar events."""
    if not db_user.google_refresh_token:
        await message.answer("⚠️ Google Calendar не подключён.\nИспользуй /connect_google")
        return

    try:
        events = await cal_service.get_events(db_user.google_refresh_token)
    except Exception as e:
        logger.error(f"Calendar fetch error: {e}")
        await message.answer("❌ Ошибка при получении событий из Google Calendar.")
        return

    if not events:
        await message.answer("📅 Нет событий на ближайшую неделю.")
        return

    lines = ["📅 <b>Ближайшие события</b>\n"]
    for e in events[:15]:
        start = e["start"]
        if "T" in start:
            dt = datetime.fromisoformat(start)
            time_str = dt.strftime("%d.%m %H:%M")
        else:
            time_str = start
        lines.append(f"• <b>{time_str}</b> — {e['title']}")

    await message.answer("\n".join(lines), parse_mode="HTML")


# --- Meeting confirmation (from voice/text parsing) ---


@router.callback_query(F.data.startswith("meeting_confirm:"))
async def confirm_meeting(callback: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext):
    temp_id = callback.data.split(":")[1]
    data = await state.get_data()
    parsed = data.get(f"parsed_{temp_id}")

    if not parsed:
        await callback.answer("❌ Данные не найдены")
        return

    if not db_user.google_refresh_token:
        await callback.message.edit_text("⚠️ Подключи Google Calendar: /connect_google")
        await callback.answer()
        return

    meeting_time = datetime.fromisoformat(parsed["meeting_time"]) if parsed.get("meeting_time") else None
    if not meeting_time:
        await callback.message.edit_text("❌ Не удалось определить время встречи.")
        await callback.answer()
        return

    try:
        result = await cal_service.create_event(
            refresh_token=db_user.google_refresh_token,
            title=parsed["title"],
            start_time=meeting_time,
            description=parsed.get("description"),
        )
        await callback.message.edit_text(
            f"✅ Встреча создана!\n\n"
            f"<b>{parsed['title']}</b>\n"
            f"🕐 {meeting_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"🔗 <a href=\"{result['link']}\">Открыть в Google Calendar</a>",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Meeting creation error: {e}")
        await callback.message.edit_text("❌ Ошибка при создании встречи в Google Calendar.")

    await callback.answer()


@router.callback_query(F.data.startswith("meeting_cancel:"))
async def cancel_meeting(callback: CallbackQuery, state: FSMContext):
    temp_id = callback.data.split(":")[1]
    data = await state.get_data()
    data.pop(f"parsed_{temp_id}", None)
    await state.set_data(data)
    await callback.message.edit_text("❌ Создание встречи отменено.")
    await callback.answer()


@router.callback_query(F.data.startswith("free_slots:"))
async def show_free_slots(callback: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext):
    if not db_user.google_refresh_token:
        await callback.message.answer("⚠️ Подключи Google Calendar: /connect_google")
        await callback.answer()
        return

    temp_id = callback.data.split(":")[1]
    data = await state.get_data()
    parsed = data.get(f"parsed_{temp_id}")

    target_date = datetime.now()
    if parsed and parsed.get("meeting_time"):
        target_date = datetime.fromisoformat(parsed["meeting_time"])

    try:
        slots = await cal_service.get_free_slots(db_user.google_refresh_token, target_date)
    except Exception as e:
        logger.error(f"Free slots error: {e}")
        await callback.message.answer("❌ Ошибка получения свободных слотов.")
        await callback.answer()
        return

    if not slots:
        await callback.message.answer(f"📅 Нет свободных слотов на {target_date.strftime('%d.%m.%Y')}")
    else:
        lines = [f"📅 <b>Свободные слоты на {target_date.strftime('%d.%m.%Y')}</b>\n"]
        for s in slots:
            start = datetime.fromisoformat(s["start"]).strftime("%H:%M")
            end = datetime.fromisoformat(s["end"]).strftime("%H:%M")
            lines.append(f"• {start} — {end}")
        await callback.message.answer("\n".join(lines), parse_mode="HTML")

    await callback.answer()
