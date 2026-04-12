"""User service for managing bot users."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    name: str,
    username: str | None = None,
) -> User:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if user:
        if user.name != name or user.username != username:
            user.name = name
            user.username = username
            await session.commit()
        return user

    user = User(telegram_id=telegram_id, name=name, username=username)
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
    """Fuzzy search for user by name (case-insensitive contains)."""
    result = await session.execute(select(User).where(User.name.ilike(f"%{name}%")))
    return result.scalar_one_or_none()


async def set_user_role(session: AsyncSession, user_id: int, role: UserRole) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.role = role
        await session.commit()
    return user


async def save_google_token(session: AsyncSession, user_id: int, refresh_token: str) -> None:
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.google_refresh_token = refresh_token
        await session.commit()
