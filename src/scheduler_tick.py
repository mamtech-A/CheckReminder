"""
Daily runner for CheckReminder.

Intended to be called by Windows Task Scheduler:

    python -m src.scheduler_tick

It loads config, validates it, opens the DB, and processes all due reminders.
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def run_daily_tick() -> None:
    """Load config, open DB, and process due reminders for today."""
    from .config import load_settings, validate_settings
    from .db import get_connection, init_db
    from .reminder_service import process_due_reminders
    from .sms_client import build_sms_client

    logger.info("CheckReminder daily tick starting.")

    settings = load_settings()
    try:
        validate_settings(settings)
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    conn = get_connection(settings.db_path)
    try:
        init_db(conn)
        sms_client = build_sms_client(settings)
        process_due_reminders(conn, sms_client, settings=settings)
        logger.info("CheckReminder daily tick complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    run_daily_tick()
