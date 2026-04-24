"""
SQLite persistence layer for CheckReminder.

Tables
------
checks        – one row per bank check to track.
reminder_logs – one row per (check, offset, target_date) combination that has
                been attempted; enforces idempotency via a unique constraint.
"""

import sqlite3
from datetime import date
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they do not already exist."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS checks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT    NOT NULL,
            description  TEXT,
            due_date     TEXT    NOT NULL,  -- YYYY-MM-DD
            phone_number TEXT    NOT NULL,
            active       INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS reminder_logs (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            check_id            INTEGER NOT NULL REFERENCES checks(id),
            offset_days         INTEGER NOT NULL,
            target_date         TEXT    NOT NULL,  -- YYYY-MM-DD (due_date - offset_days)
            sent_at             TEXT,
            provider_message_id TEXT,
            status              TEXT    NOT NULL DEFAULT 'pending',
            error               TEXT,
            UNIQUE (check_id, offset_days, target_date)
        );
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Check CRUD
# ---------------------------------------------------------------------------

def add_check(
    conn: sqlite3.Connection,
    title: str,
    due_date: str,
    phone_number: str,
    description: str = "",
) -> int:
    """
    Insert a new check record and return its generated id.

    Parameters
    ----------
    due_date : str
        ISO date string ``YYYY-MM-DD``.
    phone_number : str
        Recipient phone number in E.164 format, e.g. ``+989121234567``.
    """
    cur = conn.execute(
        """
        INSERT INTO checks (title, description, due_date, phone_number)
        VALUES (?, ?, ?, ?)
        """,
        (title, description, due_date, phone_number),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def list_checks(conn: sqlite3.Connection, active_only: bool = True) -> List[sqlite3.Row]:
    """Return all check records, optionally filtering to active ones."""
    if active_only:
        return conn.execute(
            "SELECT * FROM checks WHERE active = 1 ORDER BY due_date"
        ).fetchall()
    return conn.execute("SELECT * FROM checks ORDER BY due_date").fetchall()


# ---------------------------------------------------------------------------
# Reminder query
# ---------------------------------------------------------------------------

def list_due_reminders(
    conn: sqlite3.Connection,
    today: date,
    offsets: Optional[List[int]] = None,
    send_missed: bool = False,
) -> List[Tuple[sqlite3.Row, int, str]]:
    """
    Return a list of ``(check_row, offset_days, target_date_str)`` tuples that
    need an SMS sent.

    Parameters
    ----------
    today :
        The current local date.
    offsets :
        Day-before offsets to check.  Defaults to ``[10, 3, 1]``.
    send_missed :
        When ``True``, include reminders whose *target_date* is on or before
        *today* and have not been sent yet (catch-up mode).
        When ``False``, only return reminders whose *target_date* is exactly
        *today*.
    """
    if offsets is None:
        offsets = [10, 3, 1]

    today_str = today.isoformat()

    # Fetch all active checks
    checks = conn.execute(
        "SELECT * FROM checks WHERE active = 1"
    ).fetchall()

    # Fetch all already-sent or attempted reminder log keys for efficiency
    sent_keys: set = set()
    for row in conn.execute(
        "SELECT check_id, offset_days, target_date FROM reminder_logs WHERE status = 'sent'"
    ).fetchall():
        sent_keys.add((row["check_id"], row["offset_days"], row["target_date"]))

    results = []
    for check in checks:
        due = date.fromisoformat(check["due_date"])
        for offset in offsets:
            from datetime import timedelta
            target = due - timedelta(days=offset)
            target_str = target.isoformat()

            # Skip if already sent
            if (check["id"], offset, target_str) in sent_keys:
                continue

            # Apply send policy
            if send_missed:
                if target > today:
                    continue  # Not yet due
            else:
                if target != today:
                    continue  # Only exact match

            results.append((check, offset, target_str))

    return results


# ---------------------------------------------------------------------------
# Reminder log write
# ---------------------------------------------------------------------------

def mark_reminder_sent(
    conn: sqlite3.Connection,
    check_id: int,
    offset_days: int,
    target_date: str,
    provider_message_id: Optional[str],
    status: str,
    error: Optional[str] = None,
) -> None:
    """
    Upsert a reminder log entry.

    Uses ``INSERT OR REPLACE`` so a failed attempt can be retried and
    overwritten with a success status while still honouring the unique
    constraint against true duplicates on the same day.
    """
    conn.execute(
        """
        INSERT INTO reminder_logs
            (check_id, offset_days, target_date, sent_at, provider_message_id, status, error)
        VALUES
            (?, ?, ?, datetime('now'), ?, ?, ?)
        ON CONFLICT(check_id, offset_days, target_date) DO UPDATE SET
            sent_at             = excluded.sent_at,
            provider_message_id = excluded.provider_message_id,
            status              = excluded.status,
            error               = excluded.error
        """,
        (check_id, offset_days, target_date, provider_message_id, status, error),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------

def get_connection(db_path: str) -> sqlite3.Connection:
    """Open and return a SQLite connection with Row factory set."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
