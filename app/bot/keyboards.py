"""Telegram inline keyboards for the bot."""

from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

from app.models.task import TaskStatus, TaskPriority


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Persistent reply keyboard with main bot actions."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📋 Задачи"),
                KeyboardButton(text="👤 Мои задачи"),
            ],
            [
                KeyboardButton(text="🤖 Claude AI"),
                KeyboardButton(text="🌐 Браузер"),
            ],
            [
                KeyboardButton(text="📅 Календарь"),
                KeyboardButton(text="👥 Команда"),
            ],
            [
                KeyboardButton(text="❓ Помощь"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Отправь текст, голосовое или фото...",
    )


def task_confirm_keyboard(temp_id: str) -> InlineKeyboardMarkup:
    """Keyboard for confirming a parsed task."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm:{temp_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel:{temp_id}"),
        ],
        [
            InlineKeyboardButton(text="📅 Дедлайн", callback_data=f"edit_deadline:{temp_id}"),
            InlineKeyboardButton(text="👤 Ответственный", callback_data=f"edit_assignee:{temp_id}"),
        ],
        [
            InlineKeyboardButton(text="🔺 Приоритет", callback_data=f"edit_priority:{temp_id}"),
            InlineKeyboardButton(text="📁 Проект", callback_data=f"edit_project:{temp_id}"),
        ],
    ])


def task_status_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Keyboard for changing task status."""
    statuses = {
        TaskStatus.BACKLOG: "📋 Список задач",
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


def projects_keyboard(projects: list, temp_id: str) -> InlineKeyboardMarkup:
    """Keyboard for selecting a project."""
    buttons = [
        [InlineKeyboardButton(text=f"📁 {p.name}", callback_data=f"set_project:{temp_id}:{p.id}")]
        for p in projects
    ]
    buttons.append([InlineKeyboardButton(text="🚫 Без проекта", callback_data=f"set_project:{temp_id}:0")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back:{temp_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def task_actions_keyboard(task_id: int, is_admin: bool = True) -> InlineKeyboardMarkup:
    """Keyboard for task actions in task detail view."""
    rows = [
        [
            InlineKeyboardButton(text="📊 Статус", callback_data=f"show_status:{task_id}"),
            InlineKeyboardButton(text="💬 Комментарий", callback_data=f"comment:{task_id}"),
        ],
        [
            InlineKeyboardButton(text="📝 Все комментарии", callback_data=f"comments_list:{task_id}"),
        ],
    ]
    second_row = [InlineKeyboardButton(text="📎 Файлы", callback_data=f"attachments:{task_id}")]
    if is_admin:
        second_row.append(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_ask:{task_id}"))
    rows.append(second_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def comment_actions_keyboard(task_id: int, comment_id: int, can_edit: bool, can_delete: bool) -> InlineKeyboardMarkup:
    """Inline buttons under a single comment: edit / delete."""
    row = []
    if can_edit:
        row.append(InlineKeyboardButton(text="✏️ Править", callback_data=f"comment_edit:{task_id}:{comment_id}"))
    if can_delete:
        row.append(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"comment_del_ask:{task_id}:{comment_id}"))
    return InlineKeyboardMarkup(inline_keyboard=[row] if row else [])


def comment_delete_confirm_keyboard(task_id: int, comment_id: int) -> InlineKeyboardMarkup:
    """Confirm deletion of a single comment."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"comment_del_yes:{task_id}:{comment_id}"),
            InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"comment_del_no:{task_id}:{comment_id}"),
        ],
    ])


def delete_confirm_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Keyboard for confirming task deletion."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"delete_yes:{task_id}"),
            InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"delete_no:{task_id}"),
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
