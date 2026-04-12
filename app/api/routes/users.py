"""User API routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.api.deps import get_current_user
from app.models.user import User
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
async def list_users(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    users = await user_service.get_all_users(session)
    return [
        {
            "id": u.id,
            "name": u.name,
            "username": u.username,
            "role": u.role.value,
            "has_google": bool(u.google_refresh_token),
        }
        for u in users
    ]


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "username": current_user.username,
        "role": current_user.role.value,
        "telegram_id": current_user.telegram_id,
        "has_google": bool(current_user.google_refresh_token),
    }
