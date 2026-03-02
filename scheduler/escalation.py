from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config import settings
from integrations.gmail import apply_label, check_emails_read_status
from memory.database import Database
from memory.models import ActionLog
from utils.logger import get_logger, log_decision

logger = get_logger("inboxpilot.escalation")


def _priority_to_label(priority: int) -> str:
    if priority >= settings.priority_immediate_alert:
        return "immediate"
    elif priority >= settings.priority_standard_label_min:
        return "high_priority"
    else:
        return "low_priority"


async def escalation_cycle(db: Database) -> None:
    """
    Check all tracked high-priority emails. For each one still unread:
    - If it has been unread for longer than escalation_hours since the last
      escalation (or since first_seen_at for the first escalation), bump its
      priority by escalation_step and re-apply the appropriate Gmail label.
    - If it has been read, mark it resolved.
    """
    if not settings.escalation_enabled:
        return

    logger.info("=== Escalation cycle started ===")

    unresolved = await db.get_unresolved_tracked_emails()
    if not unresolved:
        logger.info("No unresolved tracked emails to check.")
        return

    email_ids = [row["email_id"] for row in unresolved]
    read_ids = check_emails_read_status(email_ids)

    now = datetime.now(timezone.utc)
    threshold = timedelta(hours=settings.escalation_hours)
    escalated_count = 0
    resolved_count = 0

    for row in unresolved:
        email_id = row["email_id"]

        # Mark as resolved if the email has been read (or deleted)
        if email_id in read_ids:
            await db.resolve_email(email_id)
            log_decision(
                email_id,
                "ESCALATION_RESOLVED",
                f"email is no longer unread, original_priority={row['original_priority']}",
            )
            logger.info(
                "Resolved tracking for email %s (subject='%s')", email_id, row["subject"]
            )
            resolved_count += 1
            continue

        # Determine the reference timestamp for this escalation window
        reference_time_str = row["last_escalated_at"] or row["first_seen_at"]
        try:
            reference_dt = datetime.fromisoformat(reference_time_str)
            if reference_dt.tzinfo is None:
                reference_dt = reference_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            logger.warning(
                "Could not parse timestamp for email %s: %s", email_id, reference_time_str
            )
            continue

        if now - reference_dt < threshold:
            # Not enough time has elapsed yet
            continue

        current_priority = row["current_priority"]

        if current_priority >= settings.escalation_max_priority:
            logger.debug(
                "Email %s already at max escalation priority (%d), skipping.",
                email_id,
                current_priority,
            )
            continue

        new_priority = min(
            current_priority + settings.escalation_step,
            settings.escalation_max_priority,
        )

        await db.escalate_email_priority(email_id, new_priority)

        label_key = _priority_to_label(new_priority)
        apply_label(email_id, label_key)

        elapsed_hours = (now - reference_dt).total_seconds() / 3600
        log_decision(
            email_id,
            "PRIORITY_ESCALATED",
            (
                f"priority={current_priority}->{new_priority}, label={label_key}, "
                f"elapsed={elapsed_hours:.1f}h, "
                f"escalation_count={row['escalation_count'] + 1}, "
                f"subject='{row['subject']}'"
            ),
        )

        await db.log_action(
            ActionLog(
                email_id=email_id,
                action="PRIORITY_ESCALATED",
                detail=(
                    f"original_priority={row['original_priority']}, "
                    f"current_priority={new_priority}, "
                    f"escalation_count={row['escalation_count'] + 1}"
                ),
            )
        )

        if new_priority >= settings.priority_immediate_alert:
            logger.warning(
                "!! ESCALATED TO IMMEDIATE !! Email %s | From: %s | Subject: '%s' | "
                "Priority: %d -> %d",
                email_id,
                row["sender"],
                row["subject"],
                current_priority,
                new_priority,
            )
        else:
            logger.info(
                "Escalated email %s | From: %s | Priority: %d -> %d | Label: %s",
                email_id,
                row["sender"],
                current_priority,
                new_priority,
                label_key,
            )

        escalated_count += 1

    logger.info(
        "=== Escalation cycle complete: %d escalated, %d resolved ===",
        escalated_count,
        resolved_count,
    )
