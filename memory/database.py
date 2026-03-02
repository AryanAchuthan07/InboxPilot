from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from config import settings
from memory.models import ActionLog, PerformanceMemory, SenderMemory

DDL = """
CREATE TABLE IF NOT EXISTS sender_memory (
    sender_email        TEXT PRIMARY KEY,
    importance_score    REAL NOT NULL DEFAULT 5.0,
    last_response_time_avg TEXT,
    category_frequency  TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS performance_memory (
    week_start                  TEXT PRIMARY KEY,
    weekly_missed_high_priority INTEGER NOT NULL DEFAULT 0,
    classification_accuracy     REAL NOT NULL DEFAULT 0.0,
    avg_response_time           TEXT NOT NULL DEFAULT 'N/A'
);

CREATE TABLE IF NOT EXISTS action_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    email_id  TEXT NOT NULL,
    action    TEXT NOT NULL,
    detail    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reflection_log (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp                TEXT NOT NULL,
    adjust_priority_rules    TEXT NOT NULL,
    suggest_threshold_changes TEXT NOT NULL,
    detected_failure_patterns TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_priority_tracking (
    email_id             TEXT PRIMARY KEY,
    sender               TEXT NOT NULL,
    subject              TEXT NOT NULL,
    original_priority    INTEGER NOT NULL,
    current_priority     INTEGER NOT NULL,
    category             TEXT NOT NULL,
    first_seen_at        TEXT NOT NULL,
    last_escalated_at    TEXT,
    escalation_count     INTEGER NOT NULL DEFAULT 0,
    is_resolved          INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, path: str = settings.database_path):
        self._path = path

    async def initialise(self) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.executescript(DDL)
            await db.commit()

    # ------------------------------------------------------------------
    # Sender memory
    # ------------------------------------------------------------------
    async def upsert_sender(self, sender: SenderMemory) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO sender_memory (sender_email, importance_score,
                    last_response_time_avg, category_frequency)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(sender_email) DO UPDATE SET
                    importance_score = excluded.importance_score,
                    last_response_time_avg = excluded.last_response_time_avg,
                    category_frequency = excluded.category_frequency
                """,
                (
                    sender.sender_email,
                    sender.importance_score,
                    sender.last_response_time_avg,
                    sender.category_frequency_json(),
                ),
            )
            await db.commit()

    async def get_sender(self, email: str) -> SenderMemory | None:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM sender_memory WHERE sender_email = ?", (email,)
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                return SenderMemory(
                    sender_email=row["sender_email"],
                    importance_score=row["importance_score"],
                    last_response_time_avg=row["last_response_time_avg"],
                    category_frequency=json.loads(row["category_frequency"]),
                )

    # ------------------------------------------------------------------
    # Performance memory
    # ------------------------------------------------------------------
    async def upsert_performance(self, perf: PerformanceMemory) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO performance_memory (week_start,
                    weekly_missed_high_priority, classification_accuracy,
                    avg_response_time)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(week_start) DO UPDATE SET
                    weekly_missed_high_priority = excluded.weekly_missed_high_priority,
                    classification_accuracy = excluded.classification_accuracy,
                    avg_response_time = excluded.avg_response_time
                """,
                (
                    perf.week_start,
                    perf.weekly_missed_high_priority,
                    perf.classification_accuracy,
                    perf.avg_response_time,
                ),
            )
            await db.commit()

    async def get_performance(self, week_start: str) -> PerformanceMemory | None:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM performance_memory WHERE week_start = ?", (week_start,)
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                return PerformanceMemory(**dict(row))

    # ------------------------------------------------------------------
    # Action log
    # ------------------------------------------------------------------
    async def log_action(self, log: ActionLog) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO action_log (timestamp, email_id, action, detail)
                VALUES (?, ?, ?, ?)
                """,
                (log.timestamp, log.email_id, log.action, log.detail),
            )
            await db.commit()

    async def get_recent_actions(self, limit: int = 100) -> list[dict]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM action_log ORDER BY id DESC LIMIT ?", (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Reflection log
    # ------------------------------------------------------------------
    async def log_reflection(
        self,
        timestamp: str,
        adjust_priority_rules: str,
        suggest_threshold_changes: str,
        detected_failure_patterns: list[str],
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO reflection_log (timestamp, adjust_priority_rules,
                    suggest_threshold_changes, detected_failure_patterns)
                VALUES (?, ?, ?, ?)
                """,
                (
                    timestamp,
                    adjust_priority_rules,
                    suggest_threshold_changes,
                    json.dumps(detected_failure_patterns),
                ),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Priority escalation tracking
    # ------------------------------------------------------------------
    async def track_email(
        self,
        email_id: str,
        sender: str,
        subject: str,
        priority: int,
        category: str,
    ) -> None:
        """Register a high-priority email for escalation tracking. No-op if already tracked."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO email_priority_tracking
                    (email_id, sender, subject, original_priority, current_priority,
                     category, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(email_id) DO NOTHING
                """,
                (
                    email_id,
                    sender,
                    subject,
                    priority,
                    priority,
                    category,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.commit()

    async def get_unresolved_tracked_emails(self) -> list[dict]:
        """Return all tracked emails that have not yet been marked resolved."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM email_priority_tracking WHERE is_resolved = 0"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def escalate_email_priority(self, email_id: str, new_priority: int) -> None:
        """Bump the current_priority for an email and record the escalation timestamp."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                UPDATE email_priority_tracking
                SET current_priority = ?,
                    last_escalated_at = ?,
                    escalation_count = escalation_count + 1
                WHERE email_id = ?
                """,
                (new_priority, datetime.now(timezone.utc).isoformat(), email_id),
            )
            await db.commit()

    async def resolve_email(self, email_id: str) -> None:
        """Mark a tracked email as resolved (no longer needs escalation)."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "UPDATE email_priority_tracking SET is_resolved = 1 WHERE email_id = ?",
                (email_id,),
            )
            await db.commit()
