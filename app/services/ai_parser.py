from __future__ import annotations

"""AI Parser service using Google Gemini REST API for extracting tasks."""

import json
import logging
import re
import base64
from dataclasses import dataclass
from datetime import datetime

import aiohttp

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

MODEL_NAME = "gemini-2.5-flash"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent"

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

Верни ТОЛЬКО валидный JSON, без markdown блоков и без пояснений."""


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


def _extract_json(text: str) -> dict:
    """Extract JSON object from any text, handling markdown and thinking blocks."""
    text = text.strip()
    # Remove markdown code blocks
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    text = text.strip()
    # Find JSON object
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text)
    if match:
        return json.loads(match.group(0))
    # Fallback: try to parse the whole text
    return json.loads(text)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def _call_gemini(prompt: str, response_json: bool = True) -> str:
    """Call Gemini REST API directly, bypassing SDK issues."""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
    }
    if response_json:
        payload["generationConfig"] = {
            "responseMimeType": "application/json",
        }

    url = f"{API_URL}?key={settings.GEMINI_API_KEY}"

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.error("Gemini API error %s: %s", resp.status, error_text[:500])
                raise RuntimeError(f"Gemini API error {resp.status}: {error_text[:200]}")

            data = await resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError("No candidates in Gemini response")

            parts = candidates[0].get("content", {}).get("parts", [])
            # Gemini 2.5 may have thinking parts — find the text part
            text_parts = [p["text"] for p in parts if "text" in p]
            if not text_parts:
                raise RuntimeError("No text in Gemini response")

            return text_parts[-1]  # Last text part is usually the actual response


async def _call_gemini_multimodal(parts_list: list, response_json: bool = True) -> str:
    """Call Gemini REST API with multimodal content (images, audio)."""
    api_parts = []
    for p in parts_list:
        if isinstance(p, str):
            api_parts.append({"text": p})
        elif isinstance(p, dict) and "data" in p:
            api_parts.append({
                "inline_data": {
                    "mime_type": p["mime_type"],
                    "data": base64.b64encode(p["data"]).decode("utf-8"),
                }
            })

    payload = {
        "contents": [{"parts": api_parts}],
    }
    if response_json:
        payload["generationConfig"] = {
            "responseMimeType": "application/json",
        }

    url = f"{API_URL}?key={settings.GEMINI_API_KEY}"

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.error("Gemini API error %s: %s", resp.status, error_text[:500])
                raise RuntimeError(f"Gemini API error {resp.status}: {error_text[:200]}")

            data = await resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError("No candidates in Gemini response")

            parts = candidates[0].get("content", {}).get("parts", [])
            text_parts = [p["text"] for p in parts if "text" in p]
            if not text_parts:
                raise RuntimeError("No text in Gemini response")

            return text_parts[-1]


async def parse_text(text: str) -> ParsedTask:
    """Parse a task or meeting from plain text."""
    prompt = TASK_EXTRACTION_PROMPT.format(
        current_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        timezone=settings.TIMEZONE,
    )

    raw_response = await _call_gemini(f"{prompt}\n\nТекст: {text}")
    logger.info("Gemini response: %s", raw_response[:500])
    data = _extract_json(raw_response)

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
    prompt = TASK_EXTRACTION_PROMPT.format(
        current_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        timezone=settings.TIMEZONE,
    )

    parts = [prompt]
    if caption:
        parts.append(f"\nПодпись к изображению: {caption}")
    parts.append("\nИзвлеки задачу из этого изображения:")
    parts.append({"mime_type": "image/jpeg", "data": image_bytes})

    raw_response = await _call_gemini_multimodal(parts)
    data = _extract_json(raw_response)

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
    raw = await _call_gemini_multimodal(
        [
            "Транскрибируй это голосовое сообщение. Верни ТОЛЬКО текст транскрипции, без пояснений.",
            {"mime_type": "audio/ogg", "data": audio_bytes},
        ],
        response_json=False,
    )
    return raw.strip()
