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
{{
    "type": "task" или "meeting",
    "title": "Название задачи/встречи",
    "description": "Описание (если есть)",
    "deadline": "ISO 8601 datetime или null",
    "priority": "low" / "medium" / "high" / "critical" или null,
    "assignee_name": "Имя ответственного ТОЧНО как в списке команды, или null",
    "project_name": "Название проекта ТОЧНО как в списке проектов, или null",
    "meeting_time": "ISO 8601 datetime (только для встреч) или null",
    "meeting_participants": ["имена участников"] или null,
    "confidence": 0.0-1.0
}}

Правила:
- Если пользователь просит создать встречу/звонок/созвон — type = "meeting"
- Если это задача/дело/поручение — type = "task"
- Дедлайн извлекай из контекста ("завтра", "до пятницы", "к 15 апреля")
- Приоритет определяй по срочности слов ("срочно"="high", "критично"="critical", "когда будет время"="low")
- assignee_name ДОЛЖЕН точно совпадать с одним из имён команды (учитывай падежи и сокращения: "Зоряну"→"Зоряна", "Юре"→"Yurii Shepet")
- project_name ДОЛЖЕН точно совпадать с одним из проектов (учитывай падежи: "Вдало"→"Вдало")
- Текущая дата: {current_date}
- Часовой пояс: {timezone}
{team_context}
{projects_context}

Верни ТОЛЬКО валидный JSON, без markdown блоков и без пояснений."""


@dataclass
class ParsedTask:
    type: str  # "task" or "meeting"
    title: str
    description: str | None = None
    deadline: datetime | None = None
    priority: str | None = None
    assignee_name: str | None = None
    project_name: str | None = None
    meeting_time: datetime | None = None
    meeting_participants: list[str] | None = None
    confidence: float = 0.0


def _extract_json(text: str) -> dict:
    """Extract JSON object from text. Handles clean JSON, markdown blocks, etc."""
    text = text.strip()

    # 1) Try parsing the whole text as JSON first (works with responseMimeType)
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # 2) Remove markdown code blocks and try again
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = re.sub(r"```", "", cleaned).strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # 3) Find JSON object using bracket matching (handles nested objects/arrays)
    start = cleaned.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start : i + 1])
                    except (json.JSONDecodeError, ValueError):
                        break

    raise ValueError(f"Could not extract JSON from response: {text[:200]}")


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
            # Gemini 2.5 has thinking parts with "thought": true — skip them
            text_parts = [p["text"] for p in parts if "text" in p and not p.get("thought")]
            if not text_parts:
                # Fallback: try all text parts (including thinking) — take the last one
                text_parts = [p["text"] for p in parts if "text" in p]
            if not text_parts:
                logger.error("No text parts in Gemini response. Parts: %s", parts)
                raise RuntimeError("No text in Gemini response")

            logger.info("Gemini raw text (first 300 chars): %s", text_parts[-1][:300])
            return text_parts[-1]


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
            # Skip thinking parts
            text_parts = [p["text"] for p in parts if "text" in p and not p.get("thought")]
            if not text_parts:
                text_parts = [p["text"] for p in parts if "text" in p]
            if not text_parts:
                logger.error("No text parts in multimodal response. Parts: %s", parts)
                raise RuntimeError("No text in Gemini response")

            return text_parts[-1]


async def parse_text(
    text: str,
    team_members: list[str] | None = None,
    project_names: list[str] | None = None,
) -> ParsedTask:
    """Parse a task or meeting from plain text.

    Args:
        text: The raw text to parse.
        team_members: List of team member names for assignee matching.
        project_names: List of project names for project matching.
    """
    team_ctx = ""
    if team_members:
        team_ctx = f"- Команда: {', '.join(team_members)}"
    projects_ctx = ""
    if project_names:
        projects_ctx = f"- Проекты: {', '.join(project_names)}"

    prompt = TASK_EXTRACTION_PROMPT.format(
        current_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        timezone=settings.TIMEZONE,
        team_context=team_ctx,
        projects_context=projects_ctx,
    )

    raw_response = await _call_gemini(f"{prompt}\n\nТекст: {text}")
    logger.info("Gemini response (len=%d): %s", len(raw_response), raw_response[:500])

    try:
        data = _extract_json(raw_response)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("JSON parse failed. Error: %s. Raw response: %s", e, repr(raw_response[:500]))
        raise

    return ParsedTask(
        type=data.get("type", "task"),
        title=data.get("title", text[:100]),
        description=data.get("description"),
        deadline=_parse_datetime(data.get("deadline")),
        priority=data.get("priority"),
        assignee_name=data.get("assignee_name"),
        project_name=data.get("project_name"),
        meeting_time=_parse_datetime(data.get("meeting_time")),
        meeting_participants=data.get("meeting_participants"),
        confidence=data.get("confidence", 0.5),
    )


async def parse_image(
    image_bytes: bytes,
    caption: str | None = None,
    team_members: list[str] | None = None,
    project_names: list[str] | None = None,
) -> ParsedTask:
    """Parse a task from a screenshot/image."""
    team_ctx = ""
    if team_members:
        team_ctx = f"- Команда: {', '.join(team_members)}"
    projects_ctx = ""
    if project_names:
        projects_ctx = f"- Проекты: {', '.join(project_names)}"

    prompt = TASK_EXTRACTION_PROMPT.format(
        current_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        timezone=settings.TIMEZONE,
        team_context=team_ctx,
        projects_context=projects_ctx,
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
        project_name=data.get("project_name"),
        confidence=data.get("confidence", 0.5),
    )


async def parse_voice_text(
    transcribed_text: str,
    team_members: list[str] | None = None,
    project_names: list[str] | None = None,
) -> ParsedTask:
    """Parse a task from transcribed voice message text."""
    return await parse_text(
        f"[Голосовое сообщение]: {transcribed_text}",
        team_members=team_members,
        project_names=project_names,
    )


async def transcribe_voice(
    audio_bytes: bytes,
    team_members: list[str] | None = None,
) -> str:
    """Transcribe voice message using Gemini.

    If team_members is provided, uses them as context for better name recognition.
    """
    context = ""
    if team_members:
        context = (
            f"\nКонтекст: имена людей в команде — {', '.join(team_members)}. "
            "Используй правильное написание имён из списка."
        )

    raw = await _call_gemini_multimodal(
        [
            f"Транскрибируй это голосовое сообщение. Верни ТОЛЬКО текст транскрипции, без пояснений.{context}",
            {"mime_type": "audio/ogg", "data": audio_bytes},
        ],
        response_json=False,
    )
    return raw.strip()
