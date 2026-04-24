"""
Reminder engine for CheckReminder.

Core functions
--------------
compute_days_before   – Days from today until a due date.
build_message         – Build the SMS body for a reminder.
process_due_reminders – Orchestrate reminder sends for all due checks.
"""

import logging
import sqlite3
from datetime import date, timedelta
from typing import Optional

from .config import Settings
from .db import list_due_reminders, mark_reminder_sent
from .sms_client import SmsClientBase, SmsDeliveryError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def compute_days_before(due_date: date, today: date) -> int:
    """
    Return how many days remain until *due_date* from *today*.

    Positive  → due_date is in the future.
    Zero      → due_date is today.
    Negative  → due_date has already passed.
    """
    return (due_date - today).days


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------

def build_message(check: sqlite3.Row, offset_days: int) -> str:
    """
    Build a human-readable SMS reminder body.

    Parameters
    ----------
    check :
        A row from the ``checks`` table.
    offset_days :
        Number of days before the due date that this reminder is for.
    """
    title = check["title"]
    due_date = check["due_date"]

    if offset_days == 1:
        timing = "tomorrow"
    else:
        timing = f"in {offset_days} days"

    return (
        f"Reminder: Check '{title}' is due {timing} on {due_date}. "
        f"Please ensure funds are available."
    )


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def process_due_reminders(
    conn: sqlite3.Connection,
    sms_client: SmsClientBase,
    today: Optional[date] = None,
    settings: Optional[Settings] = None,
) -> None:
    """
    Find all checks that need a reminder today and send them.

    For each ``(check, offset_days)`` pair:
    1. Check the DB log — skip if already sent.
    2. Build and send the SMS.
    3. Write a log entry for success or failure.

    Parameters
    ----------
    conn :
        Open SQLite connection with Row factory.
    sms_client :
        An :class:`~sms_client.SmsClientBase` instance.
    today :
        The reference local date.  Defaults to ``date.today()``.
    settings :
        Loaded application settings.  If ``None``, defaults are used.
    """
    if today is None:
        today = _local_today(settings)

    send_missed = settings.send_missed_reminders if settings else True
    offsets = settings.reminder_offsets if settings else [10, 3, 1]

    due_reminders = list_due_reminders(
        conn,
        today=today,
        offsets=offsets,
        send_missed=send_missed,
    )

    if not due_reminders:
        logger.info("No reminders due today (%s).", today.isoformat())
        return

    logger.info(
        "Found %d reminder(s) to send for %s.", len(due_reminders), today.isoformat()
    )

    for check, offset_days, target_date_str in due_reminders:
        check_id = check["id"]
        phone = check["phone_number"]
        masked_phone = phone[:3] + "****" + phone[-2:] if len(phone) > 4 else "****"

        body = build_message(check, offset_days)
        logger.info(
            "Sending reminder: check_id=%s, offset=%s, target=%s, to=%s",
            check_id,
            offset_days,
            target_date_str,
            masked_phone,
        )

        try:
            msg_id = sms_client.send_sms(phone, body)
            mark_reminder_sent(
                conn,
                check_id=check_id,
                offset_days=offset_days,
                target_date=target_date_str,
                provider_message_id=msg_id,
                status="sent",
            )
            logger.info(
                "Reminder sent: check_id=%s, offset=%s, msg_id=%s",
                check_id,
                offset_days,
                msg_id,
            )
        except SmsDeliveryError as exc:
            logger.error(
                "Failed to send reminder: check_id=%s, offset=%s, error=%s",
                check_id,
                offset_days,
                exc,
            )
            mark_reminder_sent(
                conn,
                check_id=check_id,
                offset_days=offset_days,
                target_date=target_date_str,
                provider_message_id=None,
                status="failed",
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Timezone-aware date helper
# ---------------------------------------------------------------------------

def _local_today(settings: Optional[Settings] = None) -> date:
    """Return today's date in the configured local timezone."""
    tz_name = settings.timezone if settings else "Asia/Tehran"
    try:
        import zoneinfo
        from datetime import datetime
        tz = zoneinfo.ZoneInfo(tz_name)
        return datetime.now(tz).date()
    except (ImportError, Exception):
        # Fallback to system local time
        return date.today()
