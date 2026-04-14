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
    comment_actions_keyboard,
    comment_delete_confirm_keyboard,
)

logger = logging.getLogger(__name__)
router = Router()

# --- Translation dicts ---

STATUS_LABELS = {
    "backlog": "📋 Список задач",
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
    "🌐 Браузер",
})


class TaskEditStates(StatesGroup):
    waiting_deadline = State()
    waiting_comment = State()
    waiting_rework_feedback = State()
    waiting_comment_edit = State()


def _dict_to_parsed(d: dict):
    """Rebuild a ParsedTask-like object from the dict we store in FSM state."""
    from datetime import datetime as _dt
    from app.services.ai_parser import ParsedTask as _PT

    def _p(s):
        if not s:
            return None
        try:
            return _dt.fromisoformat(s)
        except (ValueError, TypeError):
            return None

    return _PT(
        type=d.get("type", "task"),
        title=d.get("title", ""),
        description=d.get("description"),
        deadline=_p(d.get("deadline")),
        priority=d.get("priority"),
        assignee_name=d.get("assignee_name"),
        project_name=d.get("project_name"),
        meeting_time=_p(d.get("meeting_time")),
        meeting_participants=d.get("meeting_participants"),
        confidence=d.get("confidence", 0.0),
    )


async def _refresh_task_card(callback: "CallbackQuery", temp_id: str, parsed_dict: dict) -> None:
    """Re-render the task-draft card in place so the user sees the update."""
    try:
        await callback.message.edit_text(
            _format_task_card(_dict_to_parsed(parsed_dict)),
            reply_markup=task_confirm_keyboard(temp_id),
            parse_mode="HTML",
        )
    except Exception as e:
        # Aiogram raises if the message text/markup is identical — safe to ignore.
        logger.debug("edit_text skipped: %s", e)


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
        # Fetch team & project context for better AI parsing
        all_users = await user_service.get_all_users(session)
        team_names = [u.name for u in all_users]
        projects = await task_service.get_accessible_projects(session, db_user.id)
        project_names = [p.name for p in projects]

        parsed = await ai_parser.parse_text(
            message.text,
            team_members=team_names,
            project_names=project_names,
        )
    except Exception as e:
        error_msg = str(e).lower()
        logger.exception(f"AI parse error: {e}")
        if "resource_exhausted" in error_msg or "quota" in error_msg or "429" in error_msg:
            await message.answer(
                "⏳ Превышен лимит запросов к AI (Gemini). Подожди минуту и попробуй снова.\n"
                "💡 Для снятия лимитов включи billing на Google AI Studio."
            )
            return
        if "api_key" in error_msg or "unauthorized" in error_msg or "401" in error_msg:
            await message.answer("🔑 Ошибка API ключа Gemini. Обратись к администратору.")
            return

        # Fallback: create a minimal task from the raw text so the user doesn't lose it.
        # Show the actual error so we can diagnose instead of a generic message.
        short_err = str(e)[:200]
        await message.answer(
            f"⚠️ AI не смог разобрать задачу (<code>{short_err}</code>).\n"
            "Создаю черновик из сырого текста — можешь подтвердить или отменить.",
            parse_mode="HTML",
        )
        from app.services.ai_parser import ParsedTask
        parsed = ParsedTask(
            type="task",
            title=message.text[:120],
            description=message.text if len(message.text) > 120 else None,
            confidence=0.0,
        )

    temp_id = str(uuid.uuid4())[:8]
    await state.update_data({
        f"parsed_{temp_id}": {
            "type": parsed.type,
            "title": parsed.title,
            "description": parsed.description,
            "deadline": parsed.deadline.isoformat() if parsed.deadline else None,
            "priority": parsed.priority,
            "assignee_name": parsed.assignee_name,
            "project_name": parsed.project_name,
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

    # --- Auto-detect project ---
    project_id = parsed.get("project_id")
    if not project_id:
        projects = await task_service.get_accessible_projects(session, db_user.id)
        # 1) Try AI-detected project_name
        ai_project_name = parsed.get("project_name")
        if ai_project_name:
            for proj in projects:
                if proj.name.lower() == ai_project_name.lower():
                    project_id = proj.id
                    break
        # 2) Fallback: search project name in title/description
        if not project_id:
            search_text = (parsed.get("title", "") + " " + (parsed.get("description") or "")).lower()
            for proj in projects:
                if proj.name.lower() in search_text:
                    project_id = proj.id
                    break

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

    # Use already-detected project_id (from lines above); only override if user explicitly set it
    if parsed.get("project_id") is not None:
        project_id = parsed["project_id"]

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
        await _refresh_task_card(callback, temp_id, parsed)
    else:
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
        await _refresh_task_card(callback, temp_id, parsed)
    else:
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
        await _refresh_task_card(callback, temp_id, parsed)
    else:
        await callback.message.edit_reply_markup(reply_markup=task_confirm_keyboard(temp_id))
    project_name = parsed.get("project_name") if parsed else None
    await callback.answer(f"Проект: {project_name}" if project_name else "Без проекта")


# --- Edit deadline ---


@router.callback_query(F.data.startswith("edit_deadline:"))
async def edit_deadline(callback: CallbackQuery, state: FSMContext):
    temp_id = callback.data.split(":")[1]
    # Remember the card message so we can edit it in place once the user replies.
    await state.update_data(
        editing_deadline_for=temp_id,
        deadline_card_chat_id=callback.message.chat.id,
        deadline_card_message_id=callback.message.message_id,
    )
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
            # Edit the original card in place so the user sees the change applied.
            chat_id = data.get("deadline_card_chat_id")
            msg_id = data.get("deadline_card_message_id")
            if chat_id and msg_id:
                try:
                    await message.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=msg_id,
                        text=_format_task_card(_dict_to_parsed(parsed)),
                        reply_markup=task_confirm_keyboard(temp_id),
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.debug("deadline card edit skipped: %s", e)

    await state.set_state(None)
    await message.answer(
        f"📅 Дедлайн обновлён: {deadline.strftime('%d.%m.%Y %H:%M') if deadline else 'не определён'}"
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

    # --- Role restrictions ---
    is_admin = db_user.role == UserRole.ADMIN

    # Only admin can mark tasks as done
    if new_status == "done" and not is_admin:
        await callback.answer("⛔ Только администратор может завершать задачи. Переведи в «На проверке».", show_alert=True)
        return

    task = await task_service.update_task(session, task_id, status=TaskStatus(new_status))
    if task:
        status_label = STATUS_LABELS.get(new_status, new_status)
        await callback.message.edit_text(
            f"✅ Статус задачи <b>#{task.id}</b> изменён на <b>{status_label}</b>",
            reply_markup=task_actions_keyboard(task_id, is_admin=is_admin),
            parse_mode="HTML",
        )

        # --- Notify admins when task moves to review ---
        if new_status == "review":
            admin_users = await user_service.get_admin_users(session)
            # Don't notify the admin who changed the status themselves
            admins_to_notify = [a for a in admin_users if a.id != db_user.id]
            if admins_to_notify:
                await notification_service.notify_task_review(
                    bot=callback.bot,
                    task=task,
                    admin_users=admins_to_notify,
                )
            elif is_admin:
                # Admin moved their own task to review — still send review buttons
                await notification_service.notify_task_review(
                    bot=callback.bot,
                    task=task,
                    admin_users=[db_user],
                )

    await callback.answer()


# --- Review: Accept / Rework ---


@router.callback_query(F.data.startswith("review_accept:"))
async def review_accept_task(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Admin accepts a task from review → mark as done."""
    if db_user.role != UserRole.ADMIN:
        await callback.answer("⛔ Только администратор может принимать задачи", show_alert=True)
        return

    task_id = int(callback.data.split(":")[1])
    task = await task_service.update_task(session, task_id, status=TaskStatus.DONE)
    if not task:
        await callback.answer("Задача не найдена")
        return

    await callback.message.edit_text(
        f"✅ Задача <b>#{task.id} {task.title}</b> принята и завершена!",
        parse_mode="HTML",
    )
    await callback.answer("Задача принята ✅")

    # Notify assignee that task was accepted
    if task.assignee and task.assignee.id != db_user.id:
        await notification_service.notify_task_accepted(
            bot=callback.bot,
            task=task,
            assignee=task.assignee,
            reviewer=db_user,
        )


@router.callback_query(F.data.startswith("review_rework:"))
async def review_rework_task(callback: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext):
    """Admin requests rework — ask for feedback (text or voice)."""
    if db_user.role != UserRole.ADMIN:
        await callback.answer("⛔ Только администратор может отправлять на доработку", show_alert=True)
        return

    task_id = int(callback.data.split(":")[1])
    task = await task_service.get_task(session, task_id)
    if not task:
        await callback.answer("Задача не найдена")
        return

    await state.update_data(rework_task_id=task_id)
    await state.set_state(TaskEditStates.waiting_rework_feedback)

    await callback.message.edit_text(
        f"🔄 <b>Доработка задачи #{task.id}</b>\n\n"
        f"<b>{task.title}</b>\n\n"
        f"💬 Напиши текст или запиши голосовое сообщение — что нужно доработать:",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(TaskEditStates.waiting_rework_feedback, F.text)
async def process_rework_text(message: Message, session: AsyncSession, db_user: User, state: FSMContext):
    """Process text feedback for task rework."""
    data = await state.get_data()
    task_id = data.get("rework_task_id")
    if not task_id:
        await state.set_state(None)
        return

    feedback = message.text

    # Save comment
    await task_service.add_comment(session, task_id, db_user.id, f"🔄 Доработка: {feedback}")

    # Move task back to in_progress
    task = await task_service.update_task(session, task_id, status=TaskStatus.IN_PROGRESS)

    await state.set_state(None)

    if task:
        await message.answer(
            f"🔄 Задача <b>#{task.id}</b> отправлена на доработку.\n"
            f"💬 Комментарий сохранён.",
            parse_mode="HTML",
        )
        # Notify assignee about rework
        if task.assignee and task.assignee.id != db_user.id:
            await notification_service.notify_rework(
                bot=message.bot,
                task=task,
                assignee=task.assignee,
                feedback=feedback,
                reviewer=db_user,
            )


@router.message(TaskEditStates.waiting_rework_feedback, F.voice)
async def process_rework_voice(message: Message, session: AsyncSession, db_user: User, state: FSMContext):
    """Process voice feedback for task rework — transcribe and save."""
    data = await state.get_data()
    task_id = data.get("rework_task_id")
    if not task_id:
        await state.set_state(None)
        return

    await message.answer("🎤 Транскрибирую голосовое...")

    try:
        # Download voice file
        voice_file = await message.bot.get_file(message.voice.file_id)
        voice_bytes = await message.bot.download_file(voice_file.file_path)
        audio_data = voice_bytes.read()

        # Transcribe
        feedback = await ai_parser.transcribe_voice(audio_data)
    except Exception as e:
        logger.error("Failed to transcribe rework voice: %s", e)
        await message.answer("❌ Не удалось распознать голосовое. Попробуй написать текстом.")
        return

    # Save comment
    await task_service.add_comment(session, task_id, db_user.id, f"🔄 Доработка (голосовое): {feedback}")

    # Move task back to in_progress
    task = await task_service.update_task(session, task_id, status=TaskStatus.IN_PROGRESS)

    await state.set_state(None)

    if task:
        await message.answer(
            f"🔄 Задача <b>#{task.id}</b> отправлена на доработку.\n"
            f"💬 Комментарий: <i>{feedback[:200]}</i>",
            parse_mode="HTML",
        )
        # Notify assignee about rework
        if task.assignee and task.assignee.id != db_user.id:
            await notification_service.notify_rework(
                bot=message.bot,
                task=task,
                assignee=task.assignee,
                feedback=feedback,
                reviewer=db_user,
            )


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


def _format_comment_line(c) -> str:
    author = c.user.name if c.user else "?"
    ts = c.created_at.strftime("%d.%m %H:%M") if c.created_at else ""
    # Escape HTML-unsafe chars to be safe when parse_mode=HTML.
    text = (c.text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<b>#{c.id}</b> • {author} • {ts}\n{text}"


@router.callback_query(F.data.startswith("comments_list:"))
async def show_comments_list(callback: CallbackQuery, session: AsyncSession, db_user: User):
    """Show all comments for a task with edit/delete buttons per comment."""
    task_id = int(callback.data.split(":")[1])
    task = await task_service.get_task(session, task_id)
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return

    if not task.comments:
        await callback.message.answer(f"💬 У задачи #{task_id} пока нет комментариев.")
        await callback.answer()
        return

    is_admin = db_user.role == UserRole.ADMIN
    await callback.message.answer(f"💬 Комментарии к задаче #{task_id}:")
    for c in task.comments:
        can_edit = c.user_id == db_user.id
        can_delete = c.user_id == db_user.id or is_admin
        await callback.message.answer(
            _format_comment_line(c),
            reply_markup=comment_actions_keyboard(task_id, c.id, can_edit, can_delete),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("comment_edit:"))
async def ask_edit_comment(callback: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext):
    _, task_id_s, comment_id_s = callback.data.split(":")
    comment_id = int(comment_id_s)
    comment = await task_service.get_comment(session, comment_id)
    if not comment:
        await callback.answer("Комментарий не найден", show_alert=True)
        return
    if comment.user_id != db_user.id:
        await callback.answer("⛔ Можно править только свои комментарии", show_alert=True)
        return
    await state.update_data(
        editing_comment_id=comment_id,
        editing_comment_card_chat_id=callback.message.chat.id,
        editing_comment_card_message_id=callback.message.message_id,
    )
    await state.set_state(TaskEditStates.waiting_comment_edit)
    await callback.message.answer(f"✏️ Пришли новый текст комментария #{comment_id}:")
    await callback.answer()


@router.message(TaskEditStates.waiting_comment_edit)
async def process_edit_comment(message: Message, session: AsyncSession, db_user: User, state: FSMContext):
    data = await state.get_data()
    comment_id = data.get("editing_comment_id")
    if not comment_id:
        await state.set_state(None)
        return
    comment = await task_service.get_comment(session, comment_id)
    if not comment or comment.user_id != db_user.id:
        await message.answer("⛔ Нельзя редактировать этот комментарий.")
        await state.set_state(None)
        return
    updated = await task_service.update_comment(session, comment_id, message.text)
    await state.set_state(None)
    # Update the original comment card in place if we remembered it.
    chat_id = data.get("editing_comment_card_chat_id")
    msg_id = data.get("editing_comment_card_message_id")
    if chat_id and msg_id and updated:
        try:
            await message.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=_format_comment_line(updated),
                reply_markup=comment_actions_keyboard(
                    updated.task_id, updated.id, can_edit=True, can_delete=True
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.debug("comment card edit skipped: %s", e)
    await message.answer(f"✅ Комментарий #{comment_id} обновлён.")


@router.callback_query(F.data.startswith("comment_del_ask:"))
async def ask_delete_comment(callback: CallbackQuery, session: AsyncSession, db_user: User):
    _, task_id_s, comment_id_s = callback.data.split(":")
    task_id, comment_id = int(task_id_s), int(comment_id_s)
    comment = await task_service.get_comment(session, comment_id)
    if not comment:
        await callback.answer("Комментарий не найден", show_alert=True)
        return
    is_admin = db_user.role == UserRole.ADMIN
    if comment.user_id != db_user.id and not is_admin:
        await callback.answer("⛔ Можно удалять только свои комментарии", show_alert=True)
        return
    await callback.message.edit_reply_markup(
        reply_markup=comment_delete_confirm_keyboard(task_id, comment_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("comment_del_yes:"))
async def confirm_delete_comment(callback: CallbackQuery, session: AsyncSession, db_user: User):
    _, task_id_s, comment_id_s = callback.data.split(":")
    comment_id = int(comment_id_s)
    comment = await task_service.get_comment(session, comment_id)
    if not comment:
        await callback.answer("Уже удалён", show_alert=True)
        return
    is_admin = db_user.role == UserRole.ADMIN
    if comment.user_id != db_user.id and not is_admin:
        await callback.answer("⛔ Нет прав", show_alert=True)
        return
    await task_service.delete_comment(session, comment_id)
    try:
        await callback.message.edit_text(f"🗑 Комментарий #{comment_id} удалён.")
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("comment_del_no:"))
async def cancel_delete_comment(callback: CallbackQuery, session: AsyncSession, db_user: User):
    _, task_id_s, comment_id_s = callback.data.split(":")
    task_id, comment_id = int(task_id_s), int(comment_id_s)
    comment = await task_service.get_comment(session, comment_id)
    if not comment:
        await callback.message.edit_text(f"🗑 Комментарий #{comment_id} уже удалён.")
        await callback.answer()
        return
    is_admin = db_user.role == UserRole.ADMIN
    can_edit = comment.user_id == db_user.id
    can_delete = can_edit or is_admin
    await callback.message.edit_reply_markup(
        reply_markup=comment_actions_keyboard(task_id, comment_id, can_edit, can_delete)
    )
    await callback.answer()


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
