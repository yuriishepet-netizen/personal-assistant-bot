from __future__ import annotations

"""Google Calendar integration service."""

from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.config import get_settings

settings = get_settings()

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_oauth_flow() -> Flow:
    """Create OAuth2 flow for Google Calendar."""
    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
            }
        },
        scopes=SCOPES,
        redirect_uri=settings.GOOGLE_REDIRECT_URI,
    )


def get_auth_url(state: str = "") -> str:
    """Generate Google OAuth authorization URL."""
    flow = get_oauth_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return auth_url


def exchange_code(code: str) -> dict:
    """Exchange authorization code for tokens."""
    flow = get_oauth_flow()
    flow.fetch_token(code=code)
    credentials = flow.credentials
    return {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
    }


def _get_calendar_service(refresh_token: str):
    """Build Google Calendar API service from refresh token."""
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
    )
    return build("calendar", "v3", credentials=credentials)


async def create_event(
    refresh_token: str,
    title: str,
    start_time: datetime,
    duration_minutes: int = 60,
    description: str | None = None,
    attendees: list[str] | None = None,
) -> dict:
    """Create a Google Calendar event."""
    service = _get_calendar_service(refresh_token)
    end_time = start_time + timedelta(minutes=duration_minutes)

    event_body = {
        "summary": title,
        "start": {"dateTime": start_time.isoformat(), "timeZone": settings.TIMEZONE},
        "end": {"dateTime": end_time.isoformat(), "timeZone": settings.TIMEZONE},
    }

    if description:
        event_body["description"] = description
    if attendees:
        event_body["attendees"] = [{"email": email} for email in attendees]

    event = service.events().insert(calendarId="primary", body=event_body).execute()
    return {"id": event["id"], "link": event.get("htmlLink", "")}


async def update_event(
    refresh_token: str,
    event_id: str,
    title: str | None = None,
    start_time: datetime | None = None,
    duration_minutes: int | None = None,
    description: str | None = None,
) -> dict:
    """Update an existing Google Calendar event."""
    service = _get_calendar_service(refresh_token)
    event = service.events().get(calendarId="primary", eventId=event_id).execute()

    if title:
        event["summary"] = title
    if description is not None:
        event["description"] = description
    if start_time:
        event["start"] = {"dateTime": start_time.isoformat(), "timeZone": settings.TIMEZONE}
        dur = duration_minutes or 60
        end_time = start_time + timedelta(minutes=dur)
        event["end"] = {"dateTime": end_time.isoformat(), "timeZone": settings.TIMEZONE}

    updated = service.events().update(calendarId="primary", eventId=event_id, body=event).execute()
    return {"id": updated["id"], "link": updated.get("htmlLink", "")}


async def delete_event(refresh_token: str, event_id: str) -> None:
    """Delete a Google Calendar event."""
    service = _get_calendar_service(refresh_token)
    service.events().delete(calendarId="primary", eventId=event_id).execute()


async def get_free_slots(
    refresh_token: str,
    date: datetime,
    working_hours: tuple[int, int] = (9, 18),
    slot_duration_minutes: int = 60,
) -> list[dict]:
    """Get free time slots for a given date."""
    service = _get_calendar_service(refresh_token)

    start_of_day = date.replace(hour=working_hours[0], minute=0, second=0, microsecond=0)
    end_of_day = date.replace(hour=working_hours[1], minute=0, second=0, microsecond=0)

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    busy_times = []
    for event in events_result.get("items", []):
        start = event["start"].get("dateTime")
        end = event["end"].get("dateTime")
        if start and end:
            busy_times.append((datetime.fromisoformat(start), datetime.fromisoformat(end)))

    free_slots = []
    current = start_of_day
    for busy_start, busy_end in sorted(busy_times):
        while current + timedelta(minutes=slot_duration_minutes) <= busy_start:
            free_slots.append({
                "start": current.isoformat(),
                "end": (current + timedelta(minutes=slot_duration_minutes)).isoformat(),
            })
            current += timedelta(minutes=slot_duration_minutes)
        current = max(current, busy_end)

    while current + timedelta(minutes=slot_duration_minutes) <= end_of_day:
        free_slots.append({
            "start": current.isoformat(),
            "end": (current + timedelta(minutes=slot_duration_minutes)).isoformat(),
        })
        current += timedelta(minutes=slot_duration_minutes)

    return free_slots


async def get_events(
    refresh_token: str,
    time_min: datetime | None = None,
    time_max: datetime | None = None,
    max_results: int = 250,
) -> list[dict]:
    """Get calendar events in a time range."""
    service = _get_calendar_service(refresh_token)

    if not time_min:
        time_min = datetime.now()
    if not time_max:
        time_max = time_min + timedelta(days=7)

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=max_results,
        )
        .execute()
    )

    return [
        {
            "id": e["id"],
            "title": e.get("summary", "Без названия"),
            "start": e["start"].get("dateTime", e["start"].get("date")),
            "end": e["end"].get("dateTime", e["end"].get("date")),
            "description": e.get("description", ""),
            "link": e.get("htmlLink", ""),
        }
        for e in events_result.get("items", [])
    ]
