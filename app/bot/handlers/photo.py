"""Photo/screenshot handler — parses tasks from images."""

import logging
import uuid

from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services import ai_parser
from app.bot.keyboards import task_confirm_keyboard
from app.bot.handlers.tasks import _format_task_card

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot, session: AsyncSession, db_user: User, state: FSMContext):
    """Process photo: parse task from screenshot."""
    await message.answer("📸 Анализирую изображение...")

    try:
        photo = message.photo[-1]  # highest resolution
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        image_data = file_bytes.read()

        parsed = await ai_parser.parse_image(image_data, caption=message.caption)

    except Exception as e:
        logger.error(f"Photo processing error: {e}")
        await message.answer("❌ Не удалось распознать задачу из изображения.")
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
        }
    })

    text = _format_task_card(parsed)
    await message.answer(text, reply_markup=task_confirm_keyboard(temp_id), parse_mode="HTML")
