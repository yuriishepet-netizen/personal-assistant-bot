"""Claude AI chat handler — conversational mode via /ai command."""

import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.models.user import User
from app.services import claude_service

logger = logging.getLogger(__name__)
router = Router()


class ClaudeChatStates(StatesGroup):
    chatting = State()


@router.message(Command("ai"))
async def cmd_ai(message: Message, state: FSMContext, db_user: User):
    """Enter Claude AI chat mode."""
    await state.set_state(ClaudeChatStates.chatting)
    await message.answer(
        "🤖 <b>Режим Claude AI</b>\n\n"
        "Теперь я отвечаю как Claude. Спрашивай что угодно!\n\n"
        "💡 <b>Подсказки:</b>\n"
        "• Задавай вопросы на любую тему\n"
        "• Проси помощь с текстами, кодом, идеями\n"
        "• Контекст беседы сохраняется\n\n"
        "📌 /stop — выйти из режима чата\n"
        "🗑 /clear — очистить историю беседы",
        parse_mode="HTML",
    )


@router.message(Command("stop"), ClaudeChatStates.chatting)
async def cmd_stop(message: Message, state: FSMContext):
    """Exit Claude chat mode."""
    await state.clear()
    await message.answer(
        "👋 Вышел из режима Claude.\n\n"
        "Теперь я снова в режиме задач — отправь текст, и я создам задачу.\n"
        "/ai — вернуться в режим чата",
        parse_mode="HTML",
    )


@router.message(Command("clear"), ClaudeChatStates.chatting)
async def cmd_clear(message: Message, db_user: User):
    """Clear Claude conversation history."""
    claude_service.clear_history(message.from_user.id)
    await message.answer("🗑 История беседы очищена. Начинаем с чистого листа!")


@router.message(ClaudeChatStates.chatting, F.text)
async def handle_claude_message(message: Message, db_user: User):
    """Handle messages in Claude chat mode."""
    # Show typing indicator
    await message.bot.send_chat_action(message.chat.id, "typing")

    response = await claude_service.chat(message.from_user.id, message.text)

    # Telegram has a 4096 character limit per message
    if len(response) <= 4096:
        await message.answer(response)
    else:
        # Split long responses
        for i in range(0, len(response), 4096):
            await message.answer(response[i:i + 4096])
