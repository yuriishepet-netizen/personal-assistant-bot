"""Telegram inline keyboards for the bot."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.models.task import TaskStatus, TaskPriority


def task_confirm_keyboard(temp_id: str) -> InlineKeyboardMarkup:
    """Keyboard for confirming a parsed task."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm:{temp_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel:{temp_id}"),
        ],
        [
            InlineKeyboardButton(text="📅 Изменить дедлайн", callback_data=f"edit_deadline:{temp_id}"),
            InlineKeyboardButton(text="👤 Изменить ответственного", callback_data=f"edit_assignee:{temp_id}"),
        ],
        [
            InlineKeyboardButton(text="🔺 Изменить приоритет", callback_data=f"edit_priority:{temp_id}"),
        ],
    ])


def task_status_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Keyboard for changing task status."""
    statuses = {
        TaskStatus.BACKLOG: "📋 Бэклог",
        TaskStatus.IN_PROGRESS: "🔄 В работе",
        TaskStatus.REVIEW: "👀 На проверке",
        TaskStatus.DONE: "✅ Готово",
    }
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"status:{task_id}:{s.value}")]
        for s, label in statuses.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def task_priority_keyboard(temp_id: str) -> InlineKeyboardMarkup:
    """Keyboard for selecting task priority."""
    priorities = {
        TaskPriority.LOW: "🟢 Низкий",
        TaskPriority.MEDIUM: "🟡 Средний",
        TaskPriority.HIGH: "🟠 Высокий",
        TaskPriority.CRITICAL: "🔴 Критический",
    }
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"priority:{temp_id}:{p.value}")]
        for p, label in priorities.items()
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back:{temp_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def users_keyboard(users: list, temp_id: str) -> InlineKeyboardMarkup:
    """Keyboard for selecting an assignee from the team."""
    buttons = [
        [InlineKeyboardButton(text=f"👤 {u.name}", callback_data=f"assignee:{temp_id}:{u.id}")]
        for u in users
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back:{temp_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def task_actions_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Keyboard for task actions in task detail view."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статус", callback_data=f"show_status:{task_id}"),
            InlineKeyboardButton(text="💬 Комментарий", callback_data=f"comment:{task_id}"),
        ],
        [
            InlineKeyboardButton(text="📎 Файлы", callback_data=f"attachments:{task_id}"),
        ],
    ])


def meeting_confirm_keyboard(temp_id: str) -> InlineKeyboardMarkup:
    """Keyboard for confirming a parsed meeting."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Создать встречу", callback_data=f"meeting_confirm:{temp_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"meeting_cancel:{temp_id}"),
        ],
        [
            InlineKeyboardButton(text="🕐 Свободные слоты", callback_data=f"free_slots:{temp_id}"),
        ],
    ])


def tasks_filter_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for filtering tasks list."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Все", callback_data="filter:all"),
            InlineKeyboardButton(text="🔄 В работе", callback_data="filter:in_progress"),
        ],
        [
            InlineKeyboardButton(text="👀 На проверке", callback_data="filter:review"),
            InlineKeyboardButton(text="✅ Готово", callback_data="filter:done"),
        ],
        [
            InlineKeyboardButton(text="👤 Мои задачи", callback_data="filter:my"),
        ],
    ])
