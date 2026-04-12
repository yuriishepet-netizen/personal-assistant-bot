"""Bot middlewares for auth and DB session injection."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from app.db.session import async_session
from app.services.user_service import get_or_create_user
from app.config import get_settings

settings = get_settings()


class DbSessionMiddleware(BaseMiddleware):
    """Inject async DB session into handler data."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with async_session() as session:
            data["session"] = session
            return await handler(event, data)


class AuthMiddleware(BaseMiddleware):
    """Register user and check access."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, Message) and event.from_user:
            tg_user = event.from_user
        elif isinstance(event, CallbackQuery) and event.from_user:
            tg_user = event.from_user
        else:
            return await handler(event, data)

        # Check whitelist (if configured)
        if settings.ALLOWED_TELEGRAM_IDS and tg_user.id not in settings.ALLOWED_TELEGRAM_IDS:
            if isinstance(event, Message):
                await event.answer("⛔ У вас нет доступа к этому боту.")
            return

        session = data.get("session")
        if session:
            name = tg_user.full_name or tg_user.first_name or "Unknown"
            user = await get_or_create_user(session, tg_user.id, name, tg_user.username)
            data["db_user"] = user

        return await handler(event, data)
