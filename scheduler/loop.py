from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agents.classifier import classify_email
from agents.drafter import generate_draft
from agents.reflector import run_reflection
from config import settings
from integrations.gmail import (
    apply_label,
    archive_email,
    fetch_unread_emails,
    save_draft,
)
from memory.database import Database
from memory.models import ActionLog, SenderMemory
from scheduler.follow_up import handle_follow_up
from utils.logger import get_logger, log_decision

logger = get_logger("inboxpilot.loop")

db = Database()


# ---------------------------------------------------------------------------
# Helper: map priority score to label key
# ---------------------------------------------------------------------------
def _priority_to_label(priority: int) -> str:
    if priority >= settings.priority_immediate_alert:
        return "immediate"
    elif priority >= settings.priority_standard_label_min:
        return "standard"
    else:
        return "low_priority"


# ---------------------------------------------------------------------------
# Main polling cycle (every N minutes)
# ---------------------------------------------------------------------------
async def agent_cycle() -> None:
    logger.info("=== Agent cycle started ===")
    emails, total_unread = fetch_unread_emails()

    logger.info("Fetched %d unread emails (total inbox unread: %d)", len(emails), total_unread)

    # Track category breakdown for weekly reflection
    category_counts: dict[str, int] = defaultdict(int)

    # If inbox is over goal, sort: tackle low-priority first
    if total_unread > settings.unread_goal:
        logger.warning(
            "Inbox overflow: %d unread (goal=%d). Clearing low-priority first.",
            total_unread,
            settings.unread_goal,
        )

    for email in emails:
        logger.info("Processing email %s | subject='%s'", email.id, email.subject)

        # --- 1. Look up sender memory ---
        sender_mem = await db.get_sender(email.sender)
        historical_score = sender_mem.importance_score if sender_mem else None

        # --- 2. Classify via Claude ---
        try:
            classification = classify_email(
                sender=email.sender,
                subject=email.subject,
                body=email.body,
                historical_score=historical_score,
            )
        except Exception as exc:
            logger.error("Classification failed for email %s: %s", email.id, exc)
            continue

        priority = classification.priority_score
        category = classification.category
        category_counts[category] += 1

        log_decision(
            email.id,
            "CLASSIFIED",
            f"category={category}, priority={priority}, "
            f"requires_response={classification.requires_response}, "
            f"confidence={classification.confidence:.2f}",
        )

        # --- 3. Apply Gmail label ---
        label_key = _priority_to_label(priority)
        apply_label(email.id, label_key)

        if priority >= settings.priority_immediate_alert:
            logger.warning(
                "!! IMMEDIATE ALERT !! Email %s | From: %s | Subject: %s | Priority: %d",
                email.id,
                email.sender,
                email.subject,
                priority,
            )

        if priority <= 4 and total_unread > settings.unread_goal:
            archive_email(email.id)
            log_decision(email.id, "AUTO_ARCHIVED", f"priority={priority}, unread_overflow=True")

        # --- 4. Generate draft if needed ---
        draft = None
        draft_id = None
        if classification.requires_response and priority >= settings.priority_draft_min:
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
                    body=draft.draft_email,
                )
                log_decision(
                    email.id,
                    "DRAFT_GENERATED",
                    f"draft_id={draft_id}, tone_score={draft.tone_match_score:.2f}",
                )
            except Exception as exc:
                logger.error("Draft generation failed for %s: %s", email.id, exc)

        # --- 5. Schedule follow-up if high priority ---
        if priority >= settings.priority_follow_up_min:
            follow_up_date = draft.suggest_follow_up_date if draft is not None else None
            await handle_follow_up(
                email=email,
                classification=classification,
                db=db,
                follow_up_date=follow_up_date,
            )

        # --- 6. Update sender memory ---
        freq = sender_mem.category_frequency if sender_mem else {}
        freq[category] = freq.get(category, 0) + 1
        # Blend new priority into running importance score
        new_score = round(
            (sender_mem.importance_score * 0.8 + priority * 0.2)
            if sender_mem
            else float(priority),
            2,
        )
        await db.upsert_sender(
            SenderMemory(
                sender_email=email.sender,
                importance_score=min(max(new_score, 1.0), 10.0),
                category_frequency=freq,
            )
        )

        # --- 7. Log action ---
        await db.log_action(
            ActionLog(
                email_id=email.id,
                action="PROCESSED",
                detail=(
                    f"category={category}, priority={priority}, "
                    f"label={label_key}, draft_id={draft_id}"
                ),
            )
        )

    # --- 8. Check goal condition ---
    _, post_unread = fetch_unread_emails(max_results=1)
    if post_unread <= settings.unread_goal:
        logger.info("Goal met: inbox unread=%d (goal=%d)", post_unread, settings.unread_goal)
    else:
        logger.warning(
            "Goal not met: inbox unread=%d (goal=%d)", post_unread, settings.unread_goal
        )

    logger.info("=== Agent cycle complete ===")


# ---------------------------------------------------------------------------
# Weekly reflection cycle
# ---------------------------------------------------------------------------
async def reflection_cycle() -> None:
    logger.info("=== Weekly reflection started ===")
    actions = await db.get_recent_actions(limit=500)

    total = len(actions)
    category_breakdown: dict[str, int] = defaultdict(int)
    for a in actions:
        if a["action"] == "PROCESSED":
            for part in a["detail"].split(","):
                if part.strip().startswith("category="):
                    cat = part.strip().split("=")[1]
                    category_breakdown[cat] += 1

    try:
        result = run_reflection(
            total_emails=total,
            missed_high_priority=0,  # Would need user feedback to compute accurately
            false_positives=0,
            avg_response_time="N/A",
            classification_accuracy=0.0,
            category_breakdown=dict(category_breakdown),
            failure_patterns=[],
        )
    except Exception as exc:
        logger.error("Reflection failed: %s", exc)
        return

    await db.log_reflection(
        timestamp=datetime.now(timezone.utc).isoformat(),
        adjust_priority_rules=result.adjust_priority_rules,
        suggest_threshold_changes=result.suggest_threshold_changes,
        detected_failure_patterns=result.detected_failure_patterns,
    )

    logger.info("Reflection complete.")
    logger.info("Rule adjustments: %s", result.adjust_priority_rules)
    logger.info("Threshold changes: %s", result.suggest_threshold_changes)
    if result.detected_failure_patterns:
        logger.info("Failure patterns: %s", result.detected_failure_patterns)

    logger.info("=== Weekly reflection complete ===")


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------
def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        agent_cycle,
        trigger="interval",
        minutes=settings.poll_interval_minutes,
        id="agent_cycle",
        name="Email polling cycle",
        replace_existing=True,
    )
    scheduler.add_job(
        reflection_cycle,
        trigger="cron",
        day_of_week="sun",
        hour=8,
        minute=0,
        id="weekly_reflection",
        name="Weekly reflection",
        replace_existing=True,
    )
    return scheduler
