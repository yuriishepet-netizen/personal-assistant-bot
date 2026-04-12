"""Voice message handler — transcribes and parses tasks from voice."""

import logging
import uuid

from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services import ai_parser
from app.bot.keyboards import task_confirm_keyboard, meeting_confirm_keyboard
from app.bot.handlers.tasks import _format_task_card

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot, session: AsyncSession, db_user: User, state: FSMContext):
    """Process voice message: transcribe → parse → suggest task/meeting."""
    await message.answer("🎤 Слушаю...")

    try:
        file = await bot.get_file(message.voice.file_id)
        file_bytes = await bot.download_file(file.file_path)
        audio_data = file_bytes.read()

        # Transcribe
        transcription = await ai_parser.transcribe_voice(audio_data)
        await message.answer(f"📝 Распознано: <i>{transcription}</i>", parse_mode="HTML")

        # Parse task/meeting
        parsed = await ai_parser.parse_voice_text(transcription)

    except Exception as e:
        logger.error(f"Voice processing error: {e}")
        await message.answer("❌ Не удалось обработать голосовое сообщение.")
        return

    temp_id = str(uuid.uuid4())[:8]
    await state.update_data({
        f"parsed_{temp_id}": {
            "type": parsed.type,
            "title": parsed.title,
            "description": parsed.description,
            "deadline": parsed.deadline.isoformat() if parsed.deadline else None,
            "priority": parsed.priority,
            "assignee_name": parsed.assignee_name,
            "meeting_time": parsed.meeting_time.isoformat() if parsed.meeting_time else None,
            "meeting_participants": parsed.meeting_participants,
        }
    })

    if parsed.type == "meeting":
        text = (
            f"📅 <b>Новая встреча</b>\n\n"
            f"<b>{parsed.title}</b>\n"
        )
        if parsed.meeting_time:
            text += f"🕐 {parsed.meeting_time.strftime('%d.%m.%Y %H:%M')}\n"
        if parsed.meeting_participants:
            text += f"👥 {', '.join(parsed.meeting_participants)}\n"
        keyboard = meeting_confirm_keyboard(temp_id)
    else:
        text = _format_task_card(parsed)
        keyboard = task_confirm_keyboard(temp_id)

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
