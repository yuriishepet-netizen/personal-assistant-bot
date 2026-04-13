from __future__ import annotations

"""Claude AI chat service for conversational responses in Telegram."""

import logging
from collections import defaultdict

import aiohttp

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"
MAX_HISTORY = 20  # Keep last N message pairs per user

# In-memory conversation history per user (telegram_id -> list of messages)
_conversations: dict[int, list[dict]] = defaultdict(list)

SYSTEM_PROMPT = """Ты — персональный AI-помощник Юры. Общайся на русском или украинском, в зависимости от того, на каком языке пишет пользователь.

Будь полезным, дружелюбным и конкретным. Отвечай кратко, но содержательно. Если пользователь просит что-то сложное — разбей на шаги. Можешь использовать emoji где уместно.

У тебя есть доступ к системе управления задачами. Если пользователь хочет создать задачу или встречу — скажи ему выйти из режима чата командой /stop и отправить сообщение боту обычным текстом."""


async def chat(telegram_id: int, user_message: str) -> str:
    """Send a message to Claude and get a response, maintaining conversation history."""
    if not settings.ANTHROPIC_API_KEY:
        return "API ключ Claude не настроен. Добавь ANTHROPIC_API_KEY в переменные Railway."

    # Add user message to history
    _conversations[telegram_id].append({
        "role": "user",
        "content": user_message,
    })

    # Trim history to keep it manageable
    if len(_conversations[telegram_id]) > MAX_HISTORY * 2:
        _conversations[telegram_id] = _conversations[telegram_id][-(MAX_HISTORY * 2):]

    headers = {
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": MODEL,
        "max_tokens": 2048,
        "system": SYSTEM_PROMPT,
        "messages": _conversations[telegram_id],
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error("Claude API error %s: %s", resp.status, error_text[:500])

                    if resp.status == 401:
                        return "Ошибка авторизации API Claude. Проверь ANTHROPIC_API_KEY."
                    elif resp.status == 429:
                        return "Превышен лимит запросов к Claude. Подожди немного и попробуй снова."
                    else:
                        return f"Ошибка Claude API ({resp.status}). Попробуй позже."

                data = await resp.json()

        # Extract response text
        content = data.get("content", [])
        response_text = ""
        for block in content:
            if block.get("type") == "text":
                response_text += block["text"]

        if not response_text:
            response_text = "Не удалось получить ответ от Claude."

        # Add assistant response to history
        _conversations[telegram_id].append({
            "role": "assistant",
            "content": response_text,
        })

        return response_text

    except aiohttp.ClientError as e:
        logger.error("Claude API connection error: %s", e)
        # Remove the user message from history since we didn't get a response
        _conversations[telegram_id].pop()
        return "Ошибка подключения к Claude API. Попробуй позже."
    except Exception as e:
        logger.error("Unexpected error in Claude chat: %s", e)
        _conversations[telegram_id].pop()
        return "Произошла непредвиденная ошибка. Попробуй ещё раз."


def clear_history(telegram_id: int) -> None:
    """Clear conversation history for a user."""
    _conversations.pop(telegram_id, None)
