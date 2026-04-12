"""Auth routes — Google OAuth callback, JWT token generation."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.api.deps import create_access_token
from app.services import calendar as cal_service
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["auth"])


class TelegramLoginRequest(BaseModel):
    telegram_id: int


@router.get("/google/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(default=""),
    session: AsyncSession = Depends(get_session),
):
    """Handle Google OAuth callback — exchange code for tokens and save refresh token."""
    try:
        tokens = cal_service.exchange_code(code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to exchange code: {e}")

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token received. Try revoking access and reconnecting.")

    # state should contain the user's telegram_id
    if state:
        try:
            telegram_id = int(state)
            user = await user_service.get_user_by_telegram_id(session, telegram_id)
            if user:
                await user_service.save_google_token(session, user.id, refresh_token)
                return {"status": "ok", "message": "Google Calendar подключён! Можешь вернуться в Telegram."}
        except ValueError:
            pass

    return {
        "status": "ok",
        "refresh_token": refresh_token,
        "message": "Token received. Save it manually if auto-linking failed.",
    }


@router.post("/telegram-login")
async def telegram_login(
    data: TelegramLoginRequest,
    session: AsyncSession = Depends(get_session),
):
    """Generate JWT for a Telegram user (for Lovable app auth)."""
    user = await user_service.get_user_by_telegram_id(session, data.telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Send /start to the bot first.")

    token = create_access_token(user.id)
    return {"access_token": token, "token_type": "bearer", "user_id": user.id, "name": user.name}
