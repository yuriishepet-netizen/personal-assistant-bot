from __future__ import annotations

"""User service for managing bot users."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.config import get_settings


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    name: str,
    username: str | None = None,
) -> User:
    settings = get_settings()
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if user:
        changed = False
        if user.name != name or user.username != username:
            user.name = name
            user.username = username
            changed = True
        # Auto-promote first allowed ID to admin
        if (
            settings.ALLOWED_TELEGRAM_IDS
            and telegram_id == settings.ALLOWED_TELEGRAM_IDS[0]
            and user.role != UserRole.ADMIN
        ):
            user.role = UserRole.ADMIN
            changed = True
        if changed:
            await session.commit()
        return user

    # New user — first allowed ID gets admin role
    role = UserRole.MEMBER
    if settings.ALLOWED_TELEGRAM_IDS and telegram_id == settings.ALLOWED_TELEGRAM_IDS[0]:
        role = UserRole.ADMIN

    user = User(telegram_id=telegram_id, name=name, username=username, role=role)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_all_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.name))
    return list(result.scalars().all())


async def find_user_by_name(session: AsyncSession, name: str) -> User | None:
    """Fuzzy search for user by name — handles Ukrainian/Russian declensions.

    Tries exact ilike match first, then progressively shorter stems to handle
    case suffixes like Зоряну→Зоряна, Юрию→Юрий, Маши→Маша.
    """
    # Try exact contains match first
    result = await session.execute(select(User).where(User.name.ilike(f"%{name}%")))
    user = result.scalar_one_or_none()
    if user:
        return user

    # Try stem matching: chop last 1-2 chars to handle declension
    clean = name.strip()
    if len(clean) >= 4:
        for trim in range(1, 3):
            stem = clean[: len(clean) - trim]
            if len(stem) < 3:
                break
            result = await session.execute(select(User).where(User.name.ilike(f"%{stem}%")))
            users = list(result.scalars().all())
            if len(users) == 1:
                return users[0]

    return None


async def set_user_role(session: AsyncSession, user_id: int, role: UserRole) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.role = role
        await session.commit()
    return user


async def get_admin_users(session: AsyncSession) -> list[User]:
    """Get all users with admin role."""
    result = await session.execute(select(User).where(User.role == UserRole.ADMIN))
    return list(result.scalars().all())


async def save_google_token(session: AsyncSession, user_id: int, refresh_token: str) -> None:
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.google_refresh_token = refresh_token
        await session.commit()
