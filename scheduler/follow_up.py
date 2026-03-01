from __future__ import annotations

from integrations.calendar import create_follow_up_reminder
from integrations.gmail import save_draft
from agents.drafter import generate_draft
from memory.database import Database
from memory.models import ActionLog, EmailObject, ClassificationResult
from utils.logger import get_logger, log_decision

logger = get_logger("inboxpilot.follow_up")


async def handle_follow_up(
    email: EmailObject,
    classification: ClassificationResult,
    db: Database,
    follow_up_date: str | None = None,
) -> None:
    """
    Schedule a follow-up calendar reminder and generate a follow-up draft
    for emails with priority_score >= FOLLOW_UP_MIN.
    """
    logger.info(
        "Scheduling follow-up for email %s (priority=%d)",
        email.id,
        classification.priority_score,
    )

    # Generate the follow-up draft
    try:
        draft = generate_draft(
            sender=email.sender,
            subject=email.subject,
            body=email.body,
            thread_history=email.thread_history,
        )
        draft_id = save_draft(
            to=email.sender,
            subject=email.subject,
            body=f"[FOLLOW-UP]\n\n{draft.draft_email}",
        )
        log_decision(email.id, "FOLLOW_UP_DRAFT", f"Draft saved (id={draft_id})")
    except Exception as exc:
        logger.error("Failed to generate follow-up draft for %s: %s", email.id, exc)
        draft_id = None

    # Create calendar reminder
    event_id = create_follow_up_reminder(
        email_id=email.id,
        sender=email.sender,
        subject=email.subject,
        follow_up_date=follow_up_date,
    )

    await db.log_action(
        ActionLog(
            email_id=email.id,
            action="FOLLOW_UP_SCHEDULED",
            detail=(
                f"calendar_event={event_id}, draft_id={draft_id}, "
                f"follow_up_date={follow_up_date}"
            ),
        )
    )
