from __future__ import annotations

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Telegram
    TELEGRAM_BOT_TOKEN: str
    ALLOWED_TELEGRAM_IDS: list[int] = []  # empty = allow all

    # Database
    DATABASE_URL: str  # postgresql+asyncpg://user:pass@host:port/db

    # Google Gemini
    GEMINI_API_KEY: str

    # Claude (Anthropic)
    ANTHROPIC_API_KEY: str = ""

    # Google Calendar OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/google/callback"

    # JWT
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 1 week

    # App
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    PORT: int = 0  # Railway sets this
    TIMEZONE: str = "Europe/Kyiv"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
