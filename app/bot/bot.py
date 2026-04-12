"""Main bot entry point — starts polling and FastAPI together."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

from app.config import get_settings
from app.bot.middlewares import DbSessionMiddleware, AuthMiddleware
from app.bot.handlers import common, tasks, voice, photo, calendar
from app.services.reminder import reminder_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()


def create_bot() -> Bot:
    return Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    # Register middlewares
    dp.message.middleware(DbSessionMiddleware())
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    # Register routers (order matters — common first, text handler last)
    dp.include_router(common.router)
    dp.include_router(calendar.router)
    dp.include_router(voice.router)
    dp.include_router(photo.router)
    dp.include_router(tasks.router)

    return dp


async def main():
    bot = create_bot()
    dp = create_dispatcher()

    # Start reminder loop in background
    asyncio.create_task(reminder_loop(bot))

    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
