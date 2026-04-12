# Lovable App Prompt

Создай веб-приложение для управления задачами команды (3-10 человек) с интеграцией Google Calendar.

## Контекст

Это фронтенд для уже работающего REST API на FastAPI. Бэкенд задеплоен на:
**API URL**: `https://assistant-bot-production-e7ec.up.railway.app`

Авторизация через Telegram ID — пользователь вводит свой Telegram ID и получает JWT токен.

## Страницы и функционал

### 1. Страница входа (Login)
- Поле ввода Telegram ID (число)
- Кнопка "Войти"
- POST `/api/auth/telegram-login` с `{ "telegram_id": number }`
- Сохранить JWT токен в localStorage
- Перенаправить на Dashboard

### 2. Dashboard (главная)
- **Переключение между Kanban и List view**
- Статистика вверху: количество задач по статусам (backlog, in_progress, review, done)
- Кнопка "Новая задача"

#### Kanban View
- 4 колонки: Backlog, In Progress, Review, Done
- Drag-and-drop карточек между колонками (при перетаскивании PATCH `/api/tasks/{id}` с новым статусом)
- На карточке: название, приоритет (цветная метка), ответственный (аватарка/имя), дедлайн

#### List View
- Таблица с сортировкой по колонкам
- Колонки: Название, Статус, Приоритет, Ответственный, Дедлайн, Создано

### 3. Фильтры (общие для обоих view)
- По статусу: backlog, in_progress, review, done
- По приоритету: low, medium, high, critical
- По ответственному (выпадающий список пользователей из GET `/api/users`)

### 4. Карточка задачи (модальное окно или отдельная страница)
- Название (редактируемое)
- Описание (textarea, редактируемое)
- Статус (dropdown: backlog, in_progress, review, done)
- Приоритет (dropdown: low, medium, high, critical) с цветовой индикацией:
  - low = серый
  - medium = синий
  - high = оранжевый
  - critical = красный
- Ответственный (dropdown из списка пользователей)
- Дедлайн (date-time picker)
- Комментарии: список + форма добавления
  - GET `/api/tasks/{id}/comments`
  - POST `/api/tasks/{id}/comments` с `{ "text": "string" }`
- Вложения: список файлов + кнопка загрузки
  - GET `/api/tasks/{id}/attachments`
  - POST `/api/tasks/{id}/attachments` (multipart form data)

### 5. Создание задачи (модальное окно)
- Название (обязательно)
- Описание
- Приоритет (default: medium)
- Ответственный
- Дедлайн
- POST `/api/tasks`

### 6. Страница календаря
- Недельный/месячный вид событий Google Calendar
- GET `/api/calendar/events?time_min=...&time_max=...`
- Кнопка "Создать встречу" → модальное окно:
  - Название, дата/время начала, длительность (минуты), описание, emails участников
  - POST `/api/calendar/events`
- Отображение свободных слотов: GET `/api/calendar/free-slots?date=...`
- Если Google Calendar не подключен — показать кнопку "Подключить Google Calendar"

### 7. Профиль пользователя
- Отображение имени, роли, Telegram username
- GET `/api/users/me`
- Статус подключения Google Calendar

## Технические требования

### API интеграция
- Base URL: `https://assistant-bot-production-e7ec.up.railway.app`
- Все запросы (кроме login и health) требуют заголовок: `Authorization: Bearer <token>`
- Обработка 401 → перенаправление на страницу входа
- Обработка ошибок с отображением toast уведомлений

### Дизайн
- Современный, минималистичный dark/light theme
- Адаптивный дизайн (мобильный + десктоп)
- Sidebar навигация: Dashboard, Calendar, Profile
- Приоритеты задач — цветовые метки (серый/синий/оранжевый/красный)
- Статусы — цветные бейджи

### Стек (Lovable defaults)
- React + TypeScript
- Tailwind CSS
- shadcn/ui компоненты
- React Query (TanStack Query) для API вызовов
- React Router для навигации

## API Endpoints Reference

### Auth
- POST `/api/auth/telegram-login` — `{ telegram_id: number }` → `{ access_token, token_type, user_id, name }`

### Users
- GET `/api/users` — список всех пользователей
- GET `/api/users/me` — текущий пользователь

### Tasks
- GET `/api/tasks?status=...&priority=...&assignee_id=...&limit=50&offset=0`
- POST `/api/tasks` — `{ title, description?, status?, priority?, assignee_id?, deadline? }`
- GET `/api/tasks/{id}`
- PATCH `/api/tasks/{id}` — `{ title?, description?, status?, priority?, assignee_id?, deadline? }`

### Comments
- GET `/api/tasks/{id}/comments`
- POST `/api/tasks/{id}/comments` — `{ text: string }`

### Attachments
- GET `/api/tasks/{id}/attachments`
- POST `/api/tasks/{id}/attachments` — multipart file upload

### Calendar
- GET `/api/calendar/events?time_min=...&time_max=...&max_results=50`
- POST `/api/calendar/events` — `{ title, start_time, duration_minutes?, description?, attendees? }`
- PATCH `/api/calendar/events/{event_id}` — `{ title?, start_time?, duration_minutes?, description? }`
- DELETE `/api/calendar/events/{event_id}`
- GET `/api/calendar/free-slots?date=...&slot_duration_minutes=60`

### Enums
- Task Status: backlog, in_progress, review, done
- Task Priority: low, medium, high, critical
- User Role: admin, member
