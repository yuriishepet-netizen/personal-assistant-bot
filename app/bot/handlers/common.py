"""Common handlers: /start, /help."""

from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from app.models.user import User

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, db_user: User):
    await message.answer(
        f"👋 Привет, <b>{db_user.name}</b>!\n\n"
        "Я твой персональный помощник. Вот что я умею:\n\n"
        "📝 <b>Задачи</b> — отправь мне текст, голосовое или скрин, и я создам задачу\n"
        "📅 <b>Встречи</b> — напиши «встреча с Иваном завтра в 15:00»\n"
        "📋 /tasks — список задач\n"
        "👤 /my — мои задачи\n"
        "📅 /calendar — события на неделю\n"
        "🔗 /connect_google — подключить Google Calendar\n"
        "❓ /help — помощь",
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Как пользоваться</b>\n\n"
        "<b>Создание задачи:</b>\n"
        "Просто отправь текст, голосовое сообщение или скриншот. "
        "AI распознает задачу и предложит подтвердить.\n\n"
        "<b>Создание встречи:</b>\n"
        "Напиши что-то вроде:\n"
        "• «встреча с Иваном завтра в 15:00»\n"
        "• «созвон с командой в пятницу в 10:00»\n\n"
        "<b>Команды:</b>\n"
        "/tasks — все задачи (с фильтрами)\n"
        "/my — мои задачи\n"
        "/calendar — события Google Calendar\n"
        "/connect_google — подключить Google Calendar\n"
        "/team — список команды\n",
        parse_mode="HTML",
    )
