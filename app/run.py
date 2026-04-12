"""Combined runner — starts both the Telegram bot and FastAPI server."""

import asyncio
import logging

import uvicorn

from app.bot.bot import create_bot, create_dispatcher
from app.services.reminder import reminder_loop
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)
settings = get_settings()


async def run_api():
    """Run FastAPI server."""
    port = settings.PORT if settings.PORT else settings.API_PORT
    config = uvicorn.Config(
        "app.api.main:app",
        host=settings.API_HOST,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def run_bot():
    """Run Telegram bot polling."""
    try:
        bot = create_bot()
        dp = create_dispatcher()
        asyncio.create_task(reminder_loop(bot))
        logger.info("Bot starting...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error("Bot failed: %s", e)


async def main():
    """Run both bot and API concurrently."""
    await asyncio.gather(run_api(), run_bot())


if __name__ == "__main__":
    asyncio.run(main())
