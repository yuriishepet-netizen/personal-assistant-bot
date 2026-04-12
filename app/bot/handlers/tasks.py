"""Task-related handlers: creating, listing, updating tasks via Telegram."""

import logging
import uuid

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.task import TaskStatus, TaskPriority
from app.services import ai_parser, task_service, user_service
from app.bot.keyboards import (
    task_confirm_keyboard,
    task_status_keyboard,
    task_priority_keyboard,
    tasks_filter_keyboard,
    task_actions_keyboard,
    users_keyboard,
)

logger = logging.getLogger(__name__)
router = Router()


class TaskEditStates(StatesGroup):
    waiting_deadline = State()
    waiting_comment = State()


def _format_task_card(parsed) -> str:
    """Format a parsed task as a Telegram message."""
    priority_map = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}
    p_emoji = priority_map.get(parsed.priority, "⚪")
    p_name = parsed.priority or "не указан"

    lines = [
        f"📝 <b>Новая задача</b>\n",
        f"<b>{parsed.title}</b>",
    ]
    if parsed.description:
        lines.append(f"📄 {parsed.description}")
    lines.append(f"{p_emoji} Приоритет: {p_name}")
    if parsed.deadline:
        lines.append(f"📅 Дедлайн: {parsed.deadline.strftime('%d.%m.%Y %H:%M')}")
    if parsed.assignee_name:
        lines.append(f"👤 Ответственный: {parsed.assignee_name}")
    lines.append(f"\n🤖 Уверенность AI: {int(parsed.confidence * 100)}%")

    return "\n".join(lines)


def _format_task_list_item(task) -> str:
    """Format a single task for the task list."""
    status_emoji = {
        "backlog": "📋",
        "in_progress": "🔄",
        "review": "👀",
        "done": "✅",
    }
    priority_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}
    s = status_emoji.get(task.status.value, "⚪")
    p = priority_emoji.get(task.priority.value, "⚪")
    deadline = f" 📅{task.deadline.strftime('%d.%m')}" if task.deadline else ""
    assignee = f" 👤{task.assignee.name}" if task.assignee else ""
    return f"{s}{p} <b>#{task.id}</b> {task.title}{deadline}{assignee}"


# --- Text message handler (AI task parsing) ---


@router.message(F.text, ~F.text.startswith("/"))
async def handle_text_message(message: Message, session: AsyncSession, db_user: User, state: FSMContext):
    """Parse text message and suggest creating a task or meeting."""
    current_state = await state.get_state()
    if current_state:
        return  # Let FSM handlers process this

    await message.answer("🤖 Анализирую...")

    try:
        parsed = await ai_parser.parse_text(message.text)
    except Exception as e:
        logger.error(f"AI parse error: {e}")
        await message.answer("❌ Не удалось распознать задачу. Попробуй переформулировать.")
        return

    temp_id = str(uuid.uuid4())[:8]
    await state.update_data({
        f"parsed_{temp_id}": {
            "type": parsed.type,
            "title": parsed.title,
            "description": parsed.description,
            "deadline": parsed.deadline.isoformat() if parsed.deadline else None,
            "priority": parsed.priority,
            "assignee_name": parsed.assignee_name,
            "meeting_time": parsed.meeting_time.isoformat() if parsed.meeting_time else None,
            "meeting_participants": parsed.meeting_participants,
        }
    })

    text = _format_task_card(parsed)
    keyboard = task_confirm_keyboard(temp_id)
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# --- Confirm task creation ---


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_task(callback: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext):
    temp_id = callback.data.split(":")[1]
    data = await state.get_data()
    parsed = data.get(f"parsed_{temp_id}")

    if not parsed:
        await callback.answer("❌ Данные задачи не найдены")
        return

    from datetime import datetime

    deadline = datetime.fromisoformat(parsed["deadline"]) if parsed.get("deadline") else None

    assignee_id = None
    if parsed.get("assignee_name"):
        assignee = await user_service.find_user_by_name(session, parsed["assignee_name"])
        if assignee:
            assignee_id = assignee.id

    priority = TaskPriority(parsed["priority"]) if parsed.get("priority") else TaskPriority.MEDIUM

    task = await task_service.create_task(
        session=session,
        title=parsed["title"],
        creator_id=db_user.id,
        description=parsed.get("description"),
        priority=priority,
        assignee_id=assignee_id,
        deadline=deadline,
    )

    await callback.message.edit_text(
        f"✅ Задача <b>#{task.id}</b> создана!\n\n<b>{task.title}</b>",
        reply_markup=task_actions_keyboard(task.id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_task(callback: CallbackQuery, state: FSMContext):
    temp_id = callback.data.split(":")[1]
    data = await state.get_data()
    data.pop(f"parsed_{temp_id}", None)
    await state.set_data(data)
    await callback.message.edit_text("❌ Создание задачи отменено.")
    await callback.answer()


# --- Edit priority ---


@router.callback_query(F.data.startswith("edit_priority:"))
async def edit_priority(callback: CallbackQuery):
    temp_id = callback.data.split(":")[1]
    await callback.message.edit_reply_markup(reply_markup=task_priority_keyboard(temp_id))
    await callback.answer()


@router.callback_query(F.data.startswith("priority:"))
async def set_priority(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    temp_id, priority = parts[1], parts[2]
    data = await state.get_data()
    parsed = data.get(f"parsed_{temp_id}")
    if parsed:
        parsed["priority"] = priority
        await state.update_data({f"parsed_{temp_id}": parsed})
    await callback.message.edit_reply_markup(reply_markup=task_confirm_keyboard(temp_id))
    await callback.answer(f"Приоритет: {priority}")


# --- Edit assignee ---


@router.callback_query(F.data.startswith("edit_assignee:"))
async def edit_assignee(callback: CallbackQuery, session: AsyncSession):
    temp_id = callback.data.split(":")[1]
    users = await user_service.get_all_users(session)
    await callback.message.edit_reply_markup(reply_markup=users_keyboard(users, temp_id))
    await callback.answer()


@router.callback_query(F.data.startswith("assignee:"))
async def set_assignee(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    parts = callback.data.split(":")
    temp_id, user_id = parts[1], int(parts[2])
    data = await state.get_data()
    parsed = data.get(f"parsed_{temp_id}")
    user = await user_service.get_user_by_id(session, user_id)
    if parsed and user:
        parsed["assignee_name"] = user.name
        await state.update_data({f"parsed_{temp_id}": parsed})
    await callback.message.edit_reply_markup(reply_markup=task_confirm_keyboard(temp_id))
    await callback.answer(f"Ответственный: {user.name}" if user else "Пользователь не найден")


# --- Edit deadline ---


@router.callback_query(F.data.startswith("edit_deadline:"))
async def edit_deadline(callback: CallbackQuery, state: FSMContext):
    temp_id = callback.data.split(":")[1]
    await state.update_data(editing_deadline_for=temp_id)
    await state.set_state(TaskEditStates.waiting_deadline)
    await callback.message.answer("📅 Введи новый дедлайн (напр. «завтра в 18:00» или «15.04.2026 14:00»):")
    await callback.answer()


@router.message(TaskEditStates.waiting_deadline)
async def process_deadline_input(message: Message, state: FSMContext):
    data = await state.get_data()
    temp_id = data.get("editing_deadline_for")

    try:
        parsed_deadline = await ai_parser.parse_text(f"дедлайн: {message.text}")
        deadline = parsed_deadline.deadline
    except Exception:
        await message.answer("❌ Не удалось распознать дату. Попробуй формат: ДД.ММ.ГГГГ ЧЧ:ММ")
        return

    if deadline and temp_id:
        parsed = data.get(f"parsed_{temp_id}")
        if parsed:
            parsed["deadline"] = deadline.isoformat()
            await state.update_data({f"parsed_{temp_id}": parsed})

    await state.set_state(None)
    await message.answer(
        f"📅 Дедлайн обновлён: {deadline.strftime('%d.%m.%Y %H:%M') if deadline else 'не определён'}",
        reply_markup=task_confirm_keyboard(temp_id) if temp_id else None,
    )


# --- Back button ---


@router.callback_query(F.data.startswith("back:"))
async def go_back(callback: CallbackQuery):
    temp_id = callback.data.split(":")[1]
    await callback.message.edit_reply_markup(reply_markup=task_confirm_keyboard(temp_id))
    await callback.answer()


# --- Task list ---


@router.message(Command("tasks"))
async def cmd_tasks(message: Message, session: AsyncSession):
    await message.answer("📋 <b>Задачи</b>\nВыбери фильтр:", reply_markup=tasks_filter_keyboard(), parse_mode="HTML")


@router.message(Command("my"))
async def cmd_my_tasks(message: Message, session: AsyncSession, db_user: User):
    tasks = await task_service.get_tasks(session, assignee_id=db_user.id)
    if not tasks:
        await message.answer("📭 У тебя нет задач.")
        return

    lines = ["👤 <b>Мои задачи</b>\n"]
    for t in tasks:
        lines.append(_format_task_list_item(t))
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data.startswith("filter:"))
async def filter_tasks(callback: CallbackQuery, session: AsyncSession, db_user: User):
    filter_value = callback.data.split(":")[1]

    if filter_value == "all":
        tasks = await task_service.get_tasks(session)
        title = "📋 Все задачи"
    elif filter_value == "my":
        tasks = await task_service.get_tasks(session, assignee_id=db_user.id)
        title = "👤 Мои задачи"
    else:
        status = TaskStatus(filter_value)
        tasks = await task_service.get_tasks(session, status=status)
        title = f"📋 Задачи: {filter_value}"

    if not tasks:
        await callback.message.edit_text(f"{title}\n\n📭 Нет задач.", parse_mode="HTML")
        await callback.answer()
        return

    lines = [f"<b>{title}</b>\n"]
    for t in tasks[:20]:
        lines.append(_format_task_list_item(t))

    if len(tasks) > 20:
        lines.append(f"\n... и ещё {len(tasks) - 20}")

    await callback.message.edit_text("\n".join(lines), parse_mode="HTML")
    await callback.answer()


# --- Task status change ---


@router.callback_query(F.data.startswith("show_status:"))
async def show_status_keyboard(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    await callback.message.edit_reply_markup(reply_markup=task_status_keyboard(task_id))
    await callback.answer()


@router.callback_query(F.data.startswith("status:"))
async def change_status(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    task_id, new_status = int(parts[1]), parts[2]

    task = await task_service.update_task(session, task_id, status=TaskStatus(new_status))
    if task:
        await callback.message.edit_text(
            f"✅ Статус задачи <b>#{task.id}</b> изменён на <b>{new_status}</b>",
            reply_markup=task_actions_keyboard(task_id),
            parse_mode="HTML",
        )
    await callback.answer()


# --- Comments ---


@router.callback_query(F.data.startswith("comment:"))
async def start_comment(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split(":")[1])
    await state.update_data(commenting_task_id=task_id)
    await state.set_state(TaskEditStates.waiting_comment)
    await callback.message.answer(f"💬 Напиши комментарий к задаче #{task_id}:")
    await callback.answer()


@router.message(TaskEditStates.waiting_comment)
async def process_comment(message: Message, session: AsyncSession, db_user: User, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("commenting_task_id")
    if task_id:
        await task_service.add_comment(session, task_id, db_user.id, message.text)
        await message.answer(f"💬 Комментарий добавлен к задаче #{task_id}")
    await state.set_state(None)


# --- Team ---


@router.message(Command("team"))
async def cmd_team(message: Message, session: AsyncSession):
    users = await user_service.get_all_users(session)
    if not users:
        await message.answer("👥 Команда пуста.")
        return

    lines = ["👥 <b>Команда</b>\n"]
    for u in users:
        role = "👑" if u.role.value == "admin" else "👤"
        lines.append(f"{role} {u.name} (@{u.username})" if u.username else f"{role} {u.name}")
    await message.answer("\n".join(lines), parse_mode="HTML")
