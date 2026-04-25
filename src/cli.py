"""
CLI for CheckReminder.

Commands
--------
  init-db     Initialise the SQLite database.
  add-check   Add a new bank check record.
  list-checks List all active check records.
  run-once    Run the reminder engine once (same as the daily tick).
    web-panel   Run a local web panel for adding and listing checks.

Usage
-----
    python -m src.cli --help
    python -m src.cli init-db
    python -m src.cli add-check --title "Check #42" --amount 25000000 --due-date 2025-07-01 --phone +989121234567
    python -m src.cli list-checks
    python -m src.cli run-once
    python -m src.cli web-panel
"""

import argparse
import re
from datetime import date


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PHONE_RE = re.compile(r"^\+?\d{7,15}$")


def _validate_date(value: str) -> str:
    if not _DATE_RE.match(value):
        raise argparse.ArgumentTypeError(
            f"Invalid date format {value!r}. Expected YYYY-MM-DD."
        )
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return value


def _validate_phone(value: str) -> str:
    cleaned = value.strip()
    if not _PHONE_RE.match(cleaned):
        raise argparse.ArgumentTypeError(
            f"Invalid phone number {value!r}. "
            "Expected E.164 format, e.g. +989121234567."
        )
    return cleaned


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def cmd_init_db(args: argparse.Namespace) -> None:  # noqa: ARG001
    from .config import load_settings
    from .db import get_connection, init_db

    settings = load_settings()
    conn = get_connection(settings.db_path)
    try:
        init_db(conn)
        print(f"Database initialised at: {settings.db_path}")
    finally:
        conn.close()


def cmd_add_check(args: argparse.Namespace) -> None:
    from .config import load_settings
    from .db import add_check, get_connection, init_db
    from .reminder_service import build_added_check_message
    from .sms_client import SmsDeliveryError, build_sms_client

    settings = load_settings()
    conn = get_connection(settings.db_path)
    try:
        init_db(conn)
        check_id = add_check(
            conn,
            title=args.title,
            due_date=args.due_date,
            phone_number=args.phone,
            amount=args.amount,
            description=args.description or "",
        )
        print(f"Check added with id={check_id}: {args.title!r} due {args.due_date}")

        # Send a confirmation SMS immediately when a check is added.
        sms_client = build_sms_client(settings)
        immediate_body = build_added_check_message(
            title=args.title,
            amount=args.amount,
            due_date=args.due_date,
        )
        try:
            message_id = sms_client.send_sms(args.phone, immediate_body)
            print(f"Immediate SMS sent successfully. message_id={message_id}")
        except SmsDeliveryError as exc:
            print(f"Check added, but immediate SMS failed: {exc}")
    finally:
        conn.close()


def cmd_list_checks(args: argparse.Namespace) -> None:  # noqa: ARG001
    from .config import load_settings
    from .db import get_connection, list_checks
    from .sms_client import _mask_phone

    settings = load_settings()
    conn = get_connection(settings.db_path)
    try:
        rows = list_checks(conn, active_only=not args.all)
        if not rows:
            print("No checks found.")
            return
        print(f"{'ID':<5} {'Title':<30} {'Due Date':<12} {'Phone':<16} {'Active'}")
        print("-" * 75)
        for row in rows:
            print(
                f"{row['id']:<5} {row['title']:<30} {row['due_date']:<12} "
                f"{_mask_phone(row['phone_number']):<16} {'yes' if row['active'] else 'no'}"
            )
    finally:
        conn.close()


def cmd_run_once(args: argparse.Namespace) -> None:  # noqa: ARG001
    from .scheduler_tick import run_daily_tick
    run_daily_tick()


def cmd_web_panel(args: argparse.Namespace) -> None:
    from .web_panel import run_web_panel

    run_web_panel(host=args.host, port=args.port, debug=args.debug)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="CheckReminder — SMS bank check reminder tool",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init-db
    sub.add_parser("init-db", help="Initialise the SQLite database")

    # add-check
    p_add = sub.add_parser("add-check", help="Add a new bank check record")
    p_add.add_argument("--title", required=True, help="Short title/label for the check")
    p_add.add_argument(
        "--due-date",
        required=True,
        type=_validate_date,
        metavar="YYYY-MM-DD",
        help="Due date of the check",
    )
    p_add.add_argument(
        "--phone",
        required=True,
        type=_validate_phone,
        help="Recipient phone number in E.164 format, e.g. +989121234567",
    )
    p_add.add_argument("--amount", default="", help="Check amount")
    p_add.add_argument("--description", default="", help="Optional description")

    # list-checks
    p_list = sub.add_parser("list-checks", help="List check records")
    p_list.add_argument("--all", action="store_true", help="Include inactive checks")

    # run-once
    sub.add_parser("run-once", help="Run the reminder engine for today")

    # web-panel
    p_web = sub.add_parser("web-panel", help="Run local web panel for checks")
    p_web.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    p_web.add_argument("--port", type=int, default=5000, help="Port to listen on")
    p_web.add_argument("--debug", action="store_true", help="Enable Flask debug mode")

    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    commands = {
        "init-db": cmd_init_db,
        "add-check": cmd_add_check,
        "list-checks": cmd_list_checks,
        "run-once": cmd_run_once,
        "web-panel": cmd_web_panel,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
