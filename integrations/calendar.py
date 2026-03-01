from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import settings
from utils.logger import get_logger

logger = get_logger("inboxpilot.calendar")

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _get_credentials() -> Credentials:
    """Re-uses the shared token file; requests Calendar scope if not present."""
    token_path = Path(settings.google_token_file)
    creds_path = Path(settings.google_credentials_file)
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return creds


def _build_service():
    return build("calendar", "v3", credentials=_get_credentials())


def create_follow_up_reminder(
    email_id: str,
    sender: str,
    subject: str,
    follow_up_date: str | None = None,
    hours_from_now: int | None = None,
) -> str | None:
    """
    Create a calendar reminder for an email follow-up.
    Provide either follow_up_date (YYYY-MM-DD) or hours_from_now.
    Returns the event ID or None on failure.
    """
    service = _build_service()

    if follow_up_date:
        start_dt = datetime.strptime(follow_up_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    elif hours_from_now:
        start_dt = datetime.now(timezone.utc) + timedelta(hours=hours_from_now)
    else:
        start_dt = datetime.now(timezone.utc) + timedelta(hours=settings.follow_up_hours)

    end_dt = start_dt + timedelta(minutes=30)

    event = {
        "summary": f"[InboxPilot] Follow-up: {subject}",
        "description": (
            f"Automated follow-up reminder created by InboxPilot.\n"
            f"Email ID: {email_id}\n"
            f"Sender: {sender}\n"
            f"Subject: {subject}"
        ),
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 30},
                {"method": "popup", "minutes": 10},
            ],
        },
    }

    try:
        created = (
            service.events()
            .insert(calendarId="primary", body=event)
            .execute()
        )
        logger.info(
            "Calendar reminder created (event_id=%s) for email %s",
            created["id"],
            email_id,
        )
        return created["id"]
    except HttpError as exc:
        logger.error("Failed to create calendar event for email %s: %s", email_id, exc)
        return None
