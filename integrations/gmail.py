from __future__ import annotations

import base64
import email as email_lib
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import settings
from memory.models import EmailObject
from utils.logger import get_logger

logger = get_logger("inboxpilot.gmail")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]

# Gmail label names managed by InboxPilot
LABEL_MAP = {
    "immediate":     "INBOXPILOT/IMMEDIATE",
    "high_priority": "INBOXPILOT/HIGH_PRIORITY",
    "standard":      "INBOXPILOT/STANDARD",
    "low_priority":  "INBOXPILOT/LOW_PRIORITY",
    "archived":      "INBOXPILOT/ARCHIVED",
}


def _get_credentials() -> Credentials:
    creds = None
    token_path = Path(settings.google_token_file)
    creds_path = Path(settings.google_credentials_file)

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
    return build("gmail", "v1", credentials=_get_credentials())


def _decode_body(msg_payload: dict) -> str:
    """Extract plain-text body from a Gmail message payload."""
    if "parts" in msg_payload:
        for part in msg_payload["parts"]:
            if part.get("mimeType") == "text/plain":
                data = part["body"].get("data", "")
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        # Fallback: first part
        data = msg_payload["parts"][0]["body"].get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    data = msg_payload.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    return ""


def fetch_unread_emails(max_results: int = 50) -> tuple[list[EmailObject], int]:
    """
    Returns (list of EmailObjects, total unread count in inbox).
    """
    service = _build_service()
    try:
        result = (
            service.users()
            .messages()
            .list(userId="me", labelIds=["INBOX", "UNREAD"], maxResults=max_results)
            .execute()
        )
    except HttpError as exc:
        logger.error("Gmail list error: %s", exc)
        return [], 0

    messages = result.get("messages", [])
    total_unread = result.get("resultSizeEstimate", len(messages))

    email_objects: list[EmailObject] = []
    for msg_ref in messages:
        try:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_ref["id"], format="full")
                .execute()
            )
            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            body = _decode_body(msg.get("payload", {}))

            # Fetch thread for history
            thread_id = msg.get("threadId", "")
            thread_msgs: list[str] = []
            if thread_id:
                thread = (
                    service.users()
                    .threads()
                    .get(userId="me", id=thread_id)
                    .execute()
                )
                for t_msg in thread.get("messages", []):
                    if t_msg["id"] != msg_ref["id"]:
                        thread_msgs.append(_decode_body(t_msg.get("payload", {}))[:500])

            email_objects.append(
                EmailObject(
                    id=msg_ref["id"],
                    sender=headers.get("from", "unknown"),
                    subject=headers.get("subject", "(no subject)"),
                    body=body,
                    timestamp=headers.get("date", ""),
                    thread_history=thread_msgs,
                    unread_count=total_unread,
                )
            )
        except HttpError as exc:
            logger.warning("Could not fetch email %s: %s", msg_ref["id"], exc)

    return email_objects, total_unread


def _get_or_create_label(service, label_name: str) -> str:
    """Return the Gmail label ID for label_name, creating it if absent."""
    existing = service.users().labels().list(userId="me").execute().get("labels", [])
    for lbl in existing:
        if lbl["name"] == label_name:
            return lbl["id"]
    # Create it
    created = (
        service.users()
        .labels()
        .create(userId="me", body={"name": label_name, "labelListVisibility": "labelShow",
                                   "messageListVisibility": "show"})
        .execute()
    )
    return created["id"]


def apply_label(email_id: str, label_key: str) -> None:
    """
    label_key is one of: immediate | high_priority | standard | low_priority | archived
    """
    label_name = LABEL_MAP.get(label_key)
    if not label_name:
        logger.warning("Unknown label key: %s", label_key)
        return
    service = _build_service()
    label_id = _get_or_create_label(service, label_name)
    try:
        service.users().messages().modify(
            userId="me",
            id=email_id,
            body={"addLabelIds": [label_id]},
        ).execute()
        logger.info("Applied label '%s' to email %s", label_name, email_id)
    except HttpError as exc:
        logger.error("Failed to apply label to %s: %s", email_id, exc)


def archive_email(email_id: str) -> None:
    """Remove INBOX label (effectively archives the email)."""
    service = _build_service()
    try:
        service.users().messages().modify(
            userId="me",
            id=email_id,
            body={"removeLabelIds": ["INBOX"]},
        ).execute()
        logger.info("Archived email %s", email_id)
    except HttpError as exc:
        logger.error("Failed to archive email %s: %s", email_id, exc)


def save_draft(to: str, subject: str, body: str) -> str | None:
    """Save an email draft. Returns the draft ID or None on failure."""
    service = _build_service()
    message_text = f"To: {to}\nSubject: Re: {subject}\n\n{body}"
    encoded = base64.urlsafe_b64encode(message_text.encode()).decode()
    try:
        draft = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": encoded}})
            .execute()
        )
        logger.info("Draft saved (id=%s) for subject '%s'", draft["id"], subject)
        return draft["id"]
    except HttpError as exc:
        logger.error("Failed to save draft: %s", exc)
        return None
