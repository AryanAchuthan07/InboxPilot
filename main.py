#!/usr/bin/env python3
"""
InboxPilot — Agentic Email Triage System
Entry point: initialises the database, runs one immediate cycle,
then starts the APScheduler loop.
"""
from __future__ import annotations

import asyncio
import signal

from config import settings
from memory.database import Database
from scheduler.loop import agent_cycle, build_scheduler
from utils.logger import get_logger

logger = get_logger("inboxpilot.main")


async def main() -> None:
    logger.info("InboxPilot starting up…")

    # Initialise SQLite schema
    db = Database()
    await db.initialise()
    logger.info("Database initialised.")

    # Run one cycle immediately on start-up
    await agent_cycle()

    # Start the scheduler
    scheduler = build_scheduler()
    scheduler.start()
    logger.info(
        "Scheduler started (poll every %d minutes, reflection every Sunday 08:00 UTC).",
        settings.poll_interval_minutes,
    )

    # Keep the event loop alive until SIGINT / SIGTERM
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown(*_):
        logger.info("Shutdown signal received. Stopping scheduler…")
        scheduler.shutdown(wait=False)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    await stop_event.wait()
    logger.info("InboxPilot shut down.")


if __name__ == "__main__":
    asyncio.run(main())
