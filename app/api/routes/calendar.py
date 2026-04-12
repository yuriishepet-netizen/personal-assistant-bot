"""Calendar API routes for Google Calendar integration."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.api.deps import get_current_user
from app.models.user import User
from app.services import calendar as cal_service
from app.services import user_service

router = APIRouter(prefix="/calendar", tags=["calendar"])


class EventCreate(BaseModel):
    title: str
    start_time: datetime
    duration_minutes: int = 60
    description: str | None = None
    attendees: list[str] | None = None


class EventUpdate(BaseModel):
    title: str | None = None
    start_time: datetime | None = None
    duration_minutes: int | None = None
    description: str | None = None


@router.get("/events")
async def list_events(
    time_min: datetime | None = None,
    time_max: datetime | None = None,
    max_results: int = Query(default=50, le=100),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not current_user.google_refresh_token:
        raise HTTPException(status_code=400, detail="Google Calendar not connected")
    events = await cal_service.get_events(current_user.google_refresh_token, time_min, time_max, max_results)
    return events


@router.post("/events", status_code=201)
async def create_event(
    body: EventCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not current_user.google_refresh_token:
        raise HTTPException(status_code=400, detail="Google Calendar not connected")
    result = await cal_service.create_event(
        refresh_token=current_user.google_refresh_token,
        title=body.title,
        start_time=body.start_time,
        duration_minutes=body.duration_minutes,
        description=body.description,
        attendees=body.attendees,
    )
    return result


@router.patch("/events/{event_id}")
async def update_event(
    event_id: str,
    body: EventUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not current_user.google_refresh_token:
        raise HTTPException(status_code=400, detail="Google Calendar not connected")
    result = await cal_service.update_event(
        refresh_token=current_user.google_refresh_token,
        event_id=event_id,
        title=body.title,
        start_time=body.start_time,
        duration_minutes=body.duration_minutes,
        description=body.description,
    )
    return result


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(
    event_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not current_user.google_refresh_token:
        raise HTTPException(status_code=400, detail="Google Calendar not connected")
    await cal_service.delete_event(current_user.google_refresh_token, event_id)


@router.get("/free-slots")
async def get_free_slots(
    date: datetime,
    slot_duration_minutes: int = Query(default=60, ge=15, le=240),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not current_user.google_refresh_token:
        raise HTTPException(status_code=400, detail="Google Calendar not connected")
    return await cal_service.get_free_slots(
        current_user.google_refresh_token,
        date,
        slot_duration_minutes=slot_duration_minutes,
    )
