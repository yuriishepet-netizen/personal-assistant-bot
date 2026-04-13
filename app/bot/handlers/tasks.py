"""Task-related handlers: creating, listing, updating tasks via Telegram."""

import logging
import uuid

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.models.task import TaskStatus, TaskPriority
from app.services import ai_parser, task_service, user_service
from app.services import calendar as cal_service
from app.services import notification_service
from app.bot.keyboards import (
    task_confirm_keyboard,
    task_status_keyboard,
    task_priority_keyboard,
    tasks_filter_keyboard,
    task_actions_keyboard,
    delete_confirm_keyboard,
    users_keyboard,
    projects_keyboard,
)

logger = logging.getLogger(__name__)
router = Router()

# --- Translation dicts ---

STATUS_LABELS = {
    "backlog": "📋 Бэклог",
    "in_progress": "🔄 В работе",
    "review": "👀 На проверке",
    "done": "✅ Готово",
}

PRIORITY_LABELS = {
    "low": "🟢 Низкий",
    "medium": "🟡 Средний",
    "high": "🟠 Высокий",
    "critical": "🔴 Критический",
}

# Reply-keyboard button texts — must be excluded from AI parser
_MENU_BUTTONS = frozenset({
    "📋 Задачи", "👤 Мои задачи", "🤖 Claude AI",
    "📅 Календарь", "👥 Команда", "❓ Помощь",
})


class TaskEditStates(StatesGroup):
    waiting_deadline = State()
    waiting_comment = State()


def _format_task_card(parsed) -> str:
    """Format a parsed task as a Telegram message."""
    priority_map = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}
    p_emoji = priority_map.get(parsed.priority, "⚪")
    p_name = parsed.priority or "не указан"

    is_meeting = parsed.type == "meeting"
    header = "📅 <b>Новая встреча</b>" if is_meeting else "📝 <b>Новая задача</b>"

    lines = [
        f"{header}\n",
        f"<b>{parsed.title}</b>",
    ]
    if parsed.description:
        lines.append(f"📄 {parsed.description}")
    lines.append(f"{p_emoji} Приоритет: {p_name}")
    if is_meeting and parsed.meeting_time:
        lines.append(f"🕐 Время: {parsed.meeting_time.strftime('%d.%m.%Y %H:%M')}")
    if parsed.deadline:
        lines.append(f"📅 Дедлайн: {parsed.deadline.strftime('%d.%m.%Y %H:%M')}")
    if parsed.assignee_name:
        lines.append(f"👤 Ответственный: {parsed.assignee_name}")
    if is_meeting and parsed.meeting_participants:
        lines.append(f"👥 Участники: {', '.join(parsed.meeting_participants)}")
    if hasattr(parsed, "project_name") and parsed.project_name:
        lines.append(f"📁 Проект: {parsed.project_name}")
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


@router.message(F.text, ~F.text.startswith("/"), ~F.text.in_(_MENU_BUTTONS), StateFilter(None))
async def handle_text_message(message: Message, session: AsyncSession, db_user: User, state: FSMContext):
    """Parse text message and suggest creating a task or meeting.

    Filters ensure this only fires when:
    - message is text (not command, not menu button)
    - no FSM state is active (so FSM handlers get priority)
    """
    await message.answer("🤖 Анализирую...")

    try:
        parsed = await ai_parser.parse_text(message.text)
    except Exception as e:
        error_msg = str(e).lower()
        logger.error(f"AI parse error: {e}")
        if "resource_exhausted" in error_msg or "quota" in error_msg or "429" in error_msg:
            await message.answer(
                "⏳ Превышен лимит запросов к AI (Gemini). Подожди минуту и попробуй снова.\n"
                "💡 Для снятия лимитов включи billing на Google AI Studio."
            )
        elif "api_key" in error_msg or "unauthorized" in error_msg or "401" in error_msg:
            await message.answer("🔑 Ошибка API ключа Gemini. Обратись к администратору.")
        else:
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
    meeting_time = datetime.fromisoformat(parsed["meeting_time"]) if parsed.get("meeting_time") else None

    assignee_id = None
    if parsed.get("assignee_name"):
        assignee = await user_service.find_user_by_name(session, parsed["assignee_name"])
        if assignee:
            assignee_id = assignee.id

    priority = TaskPriority(parsed["priority"]) if parsed.get("priority") else TaskPriority.MEDIUM

    # --- Create Google Calendar event for meetings ---
    calendar_event_id = None
    calendar_link = None
    is_meeting = parsed.get("type") == "meeting" and meeting_time

    if is_meeting:
        if not db_user.google_refresh_token:
            await callback.message.edit_text(
                "⚠️ Google Calendar не подключён.\n"
                "Встреча будет сохранена как задача без события в календаре.\n"
                "Используй /connect_google для подключения.",
                parse_mode="HTML",
            )
            # Still create the task below, just without calendar event
        else:
            try:
                event = await cal_service.create_event(
                    refresh_token=db_user.google_refresh_token,
                    title=parsed["title"],
                    start_time=meeting_time,
                    duration_minutes=60,
                    description=parsed.get("description"),
                )
                calendar_event_id = event.get("id")
                calendar_link = event.get("link")
                logger.info("Created Google Calendar event: %s", calendar_event_id)
            except Exception as e:
                logger.error("Failed to create calendar event: %s", e)
                # Continue creating the task even if calendar fails

    project_id = parsed.get("project_id")

    task = await task_service.create_task(
        session=session,
        title=parsed["title"],
        creator_id=db_user.id,
        description=parsed.get("description"),
        priority=priority,
        assignee_id=assignee_id,
        deadline=deadline or meeting_time,
        calendar_event_id=calendar_event_id,
        project_id=project_id,
    )

    is_admin = db_user.role == UserRole.ADMIN
    kb = task_actions_keyboard(task.id, is_admin=is_admin)

    # --- Format response message ---
    if is_meeting and calendar_link:
        await callback.message.edit_text(
            f"✅ Встреча <b>#{task.id}</b> создана!\n\n"
            f"<b>{task.title}</b>\n"
            f"📅 {meeting_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"🔗 <a href='{calendar_link}'>Открыть в Google Calendar</a>",
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    elif is_meeting:
        await callback.message.edit_text(
            f"✅ Встреча <b>#{task.id}</b> создана!\n\n"
            f"<b>{task.title}</b>\n"
            f"📅 {meeting_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"⚠️ Без события в Google Calendar",
            reply_markup=kb,
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            f"✅ Задача <b>#{task.id}</b> создана!\n\n<b>{task.title}</b>",
            reply_markup=kb,
            parse_mode="HTML",
        )
    await callback.answer()

    # --- Notify assignee about new task ---
    if assignee_id and assignee_id != db_user.id:
        assignee = await user_service.get_user_by_id(session, assignee_id)
        if assignee:
            await notification_service.notify_task_assigned(
                bot=callback.bot,
                task=task,
                assignee=assignee,
                assigner=db_user,
            )

    # --- Notify all team members about new task ---
    all_users = await user_service.get_all_users(session)
    await notification_service.notify_task_created(
        bot=callback.bot,
        task=task,
        creator=db_user,
        team_users=[u for u in all_users if u.id != assignee_id],  # exclude assignee (already notified)
    )


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


# --- Edit project ---


@router.callback_query(F.data.startswith("edit_project:"))
async def edit_project(callback: CallbackQuery, session: AsyncSession, db_user: User):
    temp_id = callback.data.split(":")[1]
    projects = await task_service.get_accessible_projects(session, db_user.id)
    await callback.message.edit_reply_markup(reply_markup=projects_keyboard(projects, temp_id))
    await callback.answer()


@router.callback_query(F.data.startswith("set_project:"))
async def set_project(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    parts = callback.data.split(":")
    temp_id, project_id = parts[1], int(parts[2])
    data = await state.get_data()
    parsed = data.get(f"parsed_{temp_id}")
    if parsed:
        if project_id == 0:
            parsed["project_id"] = None
            parsed["project_name"] = None
        else:
            parsed["project_id"] = project_id
            # Get project name for display
            from app.models.project import Project
            from sqlalchemy import select
            result = await session.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            parsed["project_name"] = project.name if project else None
        await state.update_data({f"parsed_{temp_id}": parsed})
    await callback.message.edit_reply_markup(reply_markup=task_confirm_keyboard(temp_id))
    project_name = parsed.get("project_name") if parsed else None
    await callback.answer(f"Проект: {project_name}" if project_name else "Без проекта")


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
@router.message(F.text == "📋 Задачи")
async def cmd_tasks(message: Message, session: AsyncSession):
    await message.answer("📋 <b>Задачи</b>\nВыбери фильтр:", reply_markup=tasks_filter_keyboard(), parse_mode="HTML")


@router.message(Command("my"))
@router.message(F.text == "👤 Мои задачи")
async def cmd_my_tasks(message: Message, session: AsyncSession, db_user: User):
    tasks = await task_service.get_tasks(session, assignee_id=db_user.id, current_user_id=db_user.id)
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
        task_list = await task_service.get_tasks(session, current_user_id=db_user.id)
        title = "📋 Все задачи"
    elif filter_value == "my":
        task_list = await task_service.get_tasks(session, assignee_id=db_user.id, current_user_id=db_user.id)
        title = "👤 Мои задачи"
    else:
        status = TaskStatus(filter_value)
        task_list = await task_service.get_tasks(session, status=status, current_user_id=db_user.id)
        title = f"📋 Задачи: {STATUS_LABELS.get(filter_value, filter_value)}"

    if not task_list:
        await callback.message.edit_text(f"{title}\n\n📭 Нет задач.", parse_mode="HTML")
        await callback.answer()
        return

    lines = [f"<b>{title}</b>\n"]
    for t in task_list[:20]:
        lines.append(_format_task_list_item(t))

    if len(task_list) > 20:
        lines.append(f"\n... и ещё {len(task_list) - 20}")

    # Add inline buttons for quick task access (first 8 tasks)
    task_buttons = []
    for t in task_list[:8]:
        task_buttons.append([InlineKeyboardButton(
            text=f"#{t.id} {t.title[:30]}",
            callback_data=f"task_detail:{t.id}",
        )])
    kb = InlineKeyboardMarkup(inline_keyboard=task_buttons) if task_buttons else None

    await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# --- Task detail (from task list) ---


@router.callback_query(F.data.startswith("task_detail:"))
async def task_detail(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Show task details with action buttons."""
    task_id = int(callback.data.split(":")[1])
    task = await task_service.get_task(session, task_id)
    if not task:
        await callback.answer("Задача не найдена")
        return

    s_label = STATUS_LABELS.get(task.status.value, task.status.value)
    p_label = PRIORITY_LABELS.get(task.priority.value, task.priority.value)

    lines = [
        f"<b>#{task.id} {task.title}</b>\n",
    ]
    if task.description:
        lines.append(f"📄 {task.description}\n")
    lines.append(f"📊 Статус: <b>{s_label}</b>")
    lines.append(f"🔺 Приоритет: <b>{p_label}</b>")
    if task.assignee:
        lines.append(f"👤 Ответственный: {task.assignee.name}")
    if task.deadline:
        lines.append(f"📅 Дедлайн: {task.deadline.strftime('%d.%m.%Y %H:%M')}")
    if task.project:
        lines.append(f"📁 Проект: {task.project.name}")

    is_admin = db_user.role == UserRole.ADMIN
    kb = task_actions_keyboard(task_id, is_admin=is_admin)

    await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# --- Task status change ---


@router.callback_query(F.data.startswith("show_status:"))
async def show_status_keyboard(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    await callback.message.edit_reply_markup(reply_markup=task_status_keyboard(task_id))
    await callback.answer()


@router.callback_query(F.data.startswith("status:"))
async def change_status(callback: CallbackQuery, session: AsyncSession, db_user: User):
    parts = callback.data.split(":")
    task_id, new_status = int(parts[1]), parts[2]

    task = await task_service.update_task(session, task_id, status=TaskStatus(new_status))
    if task:
        is_admin = db_user.role == UserRole.ADMIN
        status_label = STATUS_LABELS.get(new_status, new_status)
        await callback.message.edit_text(
            f"✅ Статус задачи <b>#{task.id}</b> изменён на <b>{status_label}</b>",
            reply_markup=task_actions_keyboard(task_id, is_admin=is_admin),
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


# --- Delete task ---


@router.callback_query(F.data.startswith("delete_ask:"))
async def ask_delete_task(callback: CallbackQuery, db_user: User):
    # Only admins can delete tasks
    if db_user.role != UserRole.ADMIN:
        await callback.answer("⛔ Только администратор может удалять задачи", show_alert=True)
        return
    task_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        f"🗑 Удалить задачу <b>#{task_id}</b>?\n\nЭто действие нельзя отменить.",
        reply_markup=delete_confirm_keyboard(task_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delete_yes:"))
async def confirm_delete_task(callback: CallbackQuery, session: AsyncSession):
    task_id = int(callback.data.split(":")[1])
    deleted = await task_service.delete_task(session, task_id)
    if deleted:
        await callback.message.edit_text(
            f"🗑 Задача <b>#{task_id}</b> удалена.",
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text("❌ Задача не найдена.")
    await callback.answer()


@router.callback_query(F.data.startswith("delete_no:"))
async def cancel_delete_task(callback: CallbackQuery, db_user: User):
    task_id = int(callback.data.split(":")[1])
    is_admin = db_user.role == UserRole.ADMIN
    await callback.message.edit_text(
        f"✅ Задача <b>#{task_id}</b> не удалена.",
        reply_markup=task_actions_keyboard(task_id, is_admin=is_admin),
        parse_mode="HTML",
    )
    await callback.answer()


# --- Team ---


@router.message(Command("team"))
@router.message(F.text == "👥 Команда")
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
