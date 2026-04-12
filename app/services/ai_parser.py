from __future__ import annotations

"""AI Parser service using Google Gemini for extracting tasks from text, voice, and images."""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime

import google.generativeai as genai

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
genai.configure(api_key=settings.GEMINI_API_KEY)

MODEL_NAME = "gemini-2.5-flash"

TASK_EXTRACTION_PROMPT = """Ты — AI-ассистент для извлечения задач. Проанализируй входные данные и извлеки информацию о задаче.

Верни JSON в формате:
{
    "type": "task" или "meeting",
    "title": "Название задачи/встречи",
    "description": "Описание (если есть)",
    "deadline": "ISO 8601 datetime или null",
    "priority": "low" / "medium" / "high" / "critical" или null,
    "assignee_name": "Имя ответственного или null",
    "meeting_time": "ISO 8601 datetime (только для встреч) или null",
    "meeting_participants": ["имена участников"] или null,
    "confidence": 0.0-1.0
}

Правила:
- Если пользователь просит создать встречу/звонок/созвон — type = "meeting"
- Если это задача/дело/поручение — type = "task"
- Дедлайн извлекай из контекста ("завтра", "до пятницы", "к 15 апреля")
- Приоритет определяй по срочности слов ("срочно"="high", "критично"="critical", "когда будет время"="low")
- Текущая дата: {current_date}
- Часовой пояс: {timezone}

Верни ТОЛЬКО валидный JSON, без markdown блоков."""

MEETING_EXTRACTION_PROMPT = """Ты — AI-ассистент для планирования встреч. Проанализируй текст и извлеки информацию о встрече.

Верни JSON в формате:
{
    "title": "Название встречи",
    "datetime": "ISO 8601 datetime",
    "duration_minutes": 60,
    "participants": ["имена"],
    "description": "Описание или null",
    "confidence": 0.0-1.0
}

Текущая дата: {current_date}
Часовой пояс: {timezone}

Верни ТОЛЬКО валидный JSON, без markdown блоков."""


@dataclass
class ParsedTask:
    type: str  # "task" or "meeting"
    title: str
    description: str | None = None
    deadline: datetime | None = None
    priority: str | None = None
    assignee_name: str | None = None
    meeting_time: datetime | None = None
    meeting_participants: list[str] | None = None
    confidence: float = 0.0


def _clean_json_response(text: str) -> str:
    """Extract JSON from Gemini response, handling thinking blocks and markdown."""
    text = text.strip()
    # Remove markdown code blocks
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    text = text.strip()
    # Try to find JSON object in the response
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        return match.group(0)
    return text


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def parse_text(text: str) -> ParsedTask:
    """Parse a task or meeting from plain text."""
    model = genai.GenerativeModel(
        MODEL_NAME,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
        ),
    )
    prompt = TASK_EXTRACTION_PROMPT.format(
        current_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        timezone=settings.TIMEZONE,
    )

    response = await model.generate_content_async(f"{prompt}\n\nТекст: {text}")
    raw = _clean_json_response(response.text)
    logger.info("Gemini raw response: %s", raw[:500])
    data = json.loads(raw)

    return ParsedTask(
        type=data.get("type", "task"),
        title=data.get("title", text[:100]),
        description=data.get("description"),
        deadline=_parse_datetime(data.get("deadline")),
        priority=data.get("priority"),
        assignee_name=data.get("assignee_name"),
        meeting_time=_parse_datetime(data.get("meeting_time")),
        meeting_participants=data.get("meeting_participants"),
        confidence=data.get("confidence", 0.5),
    )


async def parse_image(image_bytes: bytes, caption: str | None = None) -> ParsedTask:
    """Parse a task from a screenshot/image."""
    model = genai.GenerativeModel(
        MODEL_NAME,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
        ),
    )
    prompt = TASK_EXTRACTION_PROMPT.format(
        current_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        timezone=settings.TIMEZONE,
    )

    parts = [prompt]
    if caption:
        parts.append(f"\nПодпись к изображению: {caption}")
    parts.append("\nИзвлеки задачу из этого изображения:")
    parts.append({"mime_type": "image/jpeg", "data": image_bytes})

    response = await model.generate_content_async(parts)
    raw = _clean_json_response(response.text)
    data = json.loads(raw)

    return ParsedTask(
        type=data.get("type", "task"),
        title=data.get("title", "Задача из изображения"),
        description=data.get("description"),
        deadline=_parse_datetime(data.get("deadline")),
        priority=data.get("priority"),
        assignee_name=data.get("assignee_name"),
        confidence=data.get("confidence", 0.5),
    )


async def parse_voice_text(transcribed_text: str) -> ParsedTask:
    """Parse a task from transcribed voice message text."""
    return await parse_text(f"[Голосовое сообщение]: {transcribed_text}")


async def transcribe_voice(audio_bytes: bytes) -> str:
    """Transcribe voice message using Gemini."""
    model = genai.GenerativeModel(MODEL_NAME)
    response = await model.generate_content_async([
        "Транскрибируй это голосовое сообщение. Верни ТОЛЬКО текст транскрипции, без пояснений.",
        {"mime_type": "audio/ogg", "data": audio_bytes},
    ])
    return response.text.strip()
