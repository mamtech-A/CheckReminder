"""
Unit tests for CheckReminder.

Covers:
- compute_days_before date arithmetic
- build_message content
- process_due_reminders sends at exactly 10/3/1 days prior
- Idempotency: no duplicate sends on rerun
- send_missed_reminders=True  catches missed offsets
- send_missed_reminders=False skips expired offsets
"""

import sqlite3
import json
from datetime import date, timedelta
from typing import List, Optional
from unittest.mock import patch

import pytest

from src.config import Settings
from src.db import add_check, get_connection, init_db, list_due_reminders, mark_reminder_sent
from src.reminder_service import build_message, compute_days_before, process_due_reminders
from src.sms_client import MockSmsClient, SmsDeliveryError, SmsIrSmsClient, build_sms_client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_conn() -> sqlite3.Connection:
    """In-memory SQLite connection, schema already created."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    return conn


@pytest.fixture
def default_settings() -> Settings:
    return Settings(
        twilio_account_sid=None,
        twilio_auth_token=None,
        twilio_from_number=None,
        smsir_api_key=None,
        smsir_username=None,
        smsir_line_number=None,
        smsir_base_url="https://api.sms.ir/v1",
        smsir_use_legacy_get=False,
        timezone="Asia/Tehran",
        sms_provider="mock",
        db_path=":memory:",
        send_missed_reminders=False,
        reminder_offsets=[10, 3, 1],
    )


class RecordingSmsClient(MockSmsClient):
    """MockSmsClient that records every send call for assertion."""

    def __init__(self):
        self.calls: List[dict] = []
        self._fail_on: Optional[str] = None  # phone number to fail on

    def send_sms(self, to_number: str, body: str) -> Optional[str]:
        if self._fail_on and to_number == self._fail_on:
            raise SmsDeliveryError("Simulated failure")
        self.calls.append({"to": to_number, "body": body})
        return f"mock-{len(self.calls)}"


# ---------------------------------------------------------------------------
# compute_days_before
# ---------------------------------------------------------------------------

class TestComputeDaysBefore:
    def test_exactly_10_days(self):
        due = date(2025, 6, 10)
        today = date(2025, 5, 31)
        assert compute_days_before(due, today) == 10

    def test_exactly_3_days(self):
        due = date(2025, 6, 10)
        today = date(2025, 6, 7)
        assert compute_days_before(due, today) == 3

    def test_exactly_1_day(self):
        due = date(2025, 6, 10)
        today = date(2025, 6, 9)
        assert compute_days_before(due, today) == 1

    def test_due_today(self):
        d = date(2025, 6, 10)
        assert compute_days_before(d, d) == 0

    def test_overdue(self):
        due = date(2025, 6, 10)
        today = date(2025, 6, 15)
        assert compute_days_before(due, today) == -5


# ---------------------------------------------------------------------------
# build_message
# ---------------------------------------------------------------------------

class TestBuildMessage:
    def _make_check(self, title: str, due_date: str) -> sqlite3.Row:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        check_id = add_check(conn, title=title, due_date=due_date, phone_number="+989121234567")
        return conn.execute("SELECT * FROM checks WHERE id=?", (check_id,)).fetchone()

    def test_message_10_days(self):
        check = self._make_check("Test Check", "2025-06-10")
        msg = build_message(check, 10)
        assert "10 روز مانده" in msg
        assert "Test Check" in msg
        assert "2025-06-10" in msg

    def test_message_3_days(self):
        check = self._make_check("Test Check", "2025-06-10")
        msg = build_message(check, 3)
        assert "3 روز مانده" in msg

    def test_message_1_day(self):
        check = self._make_check("Test Check", "2025-06-10")
        msg = build_message(check, 1)
        assert "1 روز مانده" in msg


class TestSmsIrClient:
    def test_build_sms_client_returns_smsir_client(self, default_settings):
        settings = Settings(**{**default_settings.__dict__, "sms_provider": "smsir", "smsir_api_key": "key", "smsir_line_number": "1000"})
        client = build_sms_client(settings)
        assert isinstance(client, SmsIrSmsClient)

    def test_send_sms_posts_expected_payload(self, monkeypatch):
        captured = {}

        class FakeResponse:
            def __init__(self, payload: str):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._payload.encode("utf-8")

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse('{"status":1,"message":"موفق","data":{"messageId":89545112,"cost":1.0}}')

        monkeypatch.setattr("src.sms_client.urlopen", fake_urlopen)

        client = SmsIrSmsClient(api_key="test-api-key", line_number="3000")
        message_id = client.send_sms("+989121234567", "Hello world")

        assert captured["url"] == "https://api.sms.ir/v1/send"
        assert captured["headers"]["X-api-key"] == "test-api-key"
        assert captured["headers"]["Accept"] == "application/json"
        assert captured["headers"]["Content-type"] == "application/json"
        assert captured["body"] == {"mobile": "989121234567", "line": "3000", "text": "Hello world"}
        assert captured["timeout"] == 30
        assert message_id == "89545112"

    def test_send_sms_legacy_get_expected_query(self, monkeypatch):
        captured = {}

        class FakeResponse:
            def __init__(self, payload: str):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._payload.encode("utf-8")

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return FakeResponse('{"status":1,"message":"موفق","data":{"messageId":89545112,"cost":1.0}}')

        monkeypatch.setattr("src.sms_client.urlopen", fake_urlopen)

        client = SmsIrSmsClient(
            api_key="test-api-key",
            line_number="50003181890144",
            username="9356895959",
            use_legacy_get=True,
        )
        message_id = client.send_sms("09356895959", "test1")

        assert captured["url"].startswith("https://api.sms.ir/v1/send?")
        assert "username=9356895959" in captured["url"]
        assert "password=test-api-key" in captured["url"]
        assert "mobile=09356895959" in captured["url"]
        assert "line=50003181890144" in captured["url"]
        assert "text=test1" in captured["url"]
        assert captured["headers"]["Accept"] == "text/plain"
        assert captured["timeout"] == 30
        assert message_id == "89545112"

# ---------------------------------------------------------------------------
# process_due_reminders — exact offset sends
# ---------------------------------------------------------------------------

class TestProcessDueReminders:
    def _setup_check(self, conn, offset_days: int, today: date) -> tuple:
        """Add a check whose reminder fires exactly at offset_days from today."""
        due = today + timedelta(days=offset_days)
        check_id = add_check(conn, title=f"Check {offset_days}d", due_date=due.isoformat(), phone_number="+989121234567")
        return check_id, due

    def test_sends_at_10_days_before(self, mem_conn, default_settings):
        today = date(2025, 6, 1)
        self._setup_check(mem_conn, 10, today)
        client = RecordingSmsClient()
        settings = Settings(**{**default_settings.__dict__, "send_missed_reminders": False})

        process_due_reminders(mem_conn, client, today=today, settings=settings)

        assert len(client.calls) == 1
        assert "10 روز مانده" in client.calls[0]["body"]

    def test_sends_at_3_days_before(self, mem_conn, default_settings):
        today = date(2025, 6, 1)
        self._setup_check(mem_conn, 3, today)
        client = RecordingSmsClient()
        settings = Settings(**{**default_settings.__dict__, "send_missed_reminders": False})

        process_due_reminders(mem_conn, client, today=today, settings=settings)

        assert len(client.calls) == 1
        assert "3 روز مانده" in client.calls[0]["body"]

    def test_sends_at_1_day_before(self, mem_conn, default_settings):
        today = date(2025, 6, 1)
        self._setup_check(mem_conn, 1, today)
        client = RecordingSmsClient()
        settings = Settings(**{**default_settings.__dict__, "send_missed_reminders": False})

        process_due_reminders(mem_conn, client, today=today, settings=settings)

        assert len(client.calls) == 1
        assert "1 روز مانده" in client.calls[0]["body"]

    def test_no_send_when_not_offset_day(self, mem_conn, default_settings):
        """No SMS should be sent when today is not an offset day."""
        today = date(2025, 6, 1)
        self._setup_check(mem_conn, 5, today)  # 5 days is not in [10, 3, 1]
        client = RecordingSmsClient()
        settings = Settings(**{**default_settings.__dict__, "send_missed_reminders": False})

        process_due_reminders(mem_conn, client, today=today, settings=settings)

        assert len(client.calls) == 0


# ---------------------------------------------------------------------------
# Idempotency — no duplicate sends
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_no_duplicate_on_rerun(self, mem_conn, default_settings):
        """Running process_due_reminders twice on the same day sends only once."""
        today = date(2025, 6, 1)
        due = today + timedelta(days=3)
        add_check(mem_conn, title="Idempotent Check", due_date=due.isoformat(), phone_number="+989121234567")
        client = RecordingSmsClient()
        settings = Settings(**{**default_settings.__dict__, "send_missed_reminders": False})

        process_due_reminders(mem_conn, client, today=today, settings=settings)
        process_due_reminders(mem_conn, client, today=today, settings=settings)

        assert len(client.calls) == 1

    def test_no_duplicate_across_days(self, mem_conn, default_settings):
        """Once a reminder is logged as sent, it is not re-sent on subsequent days."""
        today = date(2025, 6, 1)
        due = today + timedelta(days=3)
        add_check(mem_conn, title="Check", due_date=due.isoformat(), phone_number="+989121234567")
        client = RecordingSmsClient()
        settings = Settings(**{**default_settings.__dict__, "send_missed_reminders": True})

        # First run with send_missed=True: the 10-day offset target falls 7 days in
        # the past (a missed reminder), and the 3-day offset target is today — both
        # are eligible, so 2 SMS messages are sent.
        process_due_reminders(mem_conn, client, today=today, settings=settings)
        first_run_count = len(client.calls)
        assert first_run_count == 2

        # Re-run on the next day (missed mode): already-sent reminders must not be re-sent.
        tomorrow = today + timedelta(days=1)
        process_due_reminders(mem_conn, client, today=tomorrow, settings=settings)
        assert len(client.calls) == first_run_count  # no new sends

    def test_db_unique_constraint_respected(self, mem_conn):
        """mark_reminder_sent upserts; no IntegrityError on double call."""
        add_check(mem_conn, title="C", due_date="2025-08-01", phone_number="+1")
        mark_reminder_sent(mem_conn, 1, 10, "2025-07-22", "sid1", "sent")
        # Second call should upsert without error
        mark_reminder_sent(mem_conn, 1, 10, "2025-07-22", "sid2", "sent")

        rows = mem_conn.execute("SELECT * FROM reminder_logs").fetchall()
        assert len(rows) == 1
        assert rows[0]["provider_message_id"] == "sid2"


# ---------------------------------------------------------------------------
# send_missed_reminders=True — catch-up behaviour
# ---------------------------------------------------------------------------

class TestSendMissedTrue:
    def test_catches_missed_offset(self, mem_conn, default_settings):
        """
        If the app missed running on the 10-day offset date, and
        send_missed=True, the reminder is sent today.
        """
        today = date(2025, 6, 5)
        # Due in 7 days → 10-day offset was 3 days ago
        due = today + timedelta(days=7)
        add_check(mem_conn, title="Missed Check", due_date=due.isoformat(), phone_number="+989121234567")
        client = RecordingSmsClient()
        settings = Settings(**{**default_settings.__dict__, "send_missed_reminders": True})

        process_due_reminders(mem_conn, client, today=today, settings=settings)

        # The 10-day reminder (target 3 days ago) should be caught up
        sent_bodies = [c["body"] for c in client.calls]
        assert any("10 روز مانده" in b for b in sent_bodies), f"Expected 10-day reminder; got: {sent_bodies}"

    def test_catches_multiple_missed_offsets(self, mem_conn, default_settings):
        """All unsent past offsets are sent when send_missed=True."""
        today = date(2025, 6, 5)
        # Due in 0 days → all offsets (10, 3, 1) have passed
        due = today
        add_check(mem_conn, title="All Missed", due_date=due.isoformat(), phone_number="+989121234567")
        client = RecordingSmsClient()
        settings = Settings(**{**default_settings.__dict__, "send_missed_reminders": True})

        process_due_reminders(mem_conn, client, today=today, settings=settings)

        # All three offsets (10, 3, 1) should be sent
        assert len(client.calls) == 3


# ---------------------------------------------------------------------------
# send_missed_reminders=False — skip expired offsets
# ---------------------------------------------------------------------------

class TestSendMissedFalse:
    def test_skips_past_offsets(self, mem_conn, default_settings):
        """
        When send_missed=False, only today's exact offset date triggers a send.
        Past offset dates are silently skipped.
        """
        today = date(2025, 6, 5)
        # Due in 7 days → 10-day target was 3 days ago, 3-day target is 4 days away
        due = today + timedelta(days=7)
        add_check(mem_conn, title="Exact Only", due_date=due.isoformat(), phone_number="+989121234567")
        client = RecordingSmsClient()
        settings = Settings(**{**default_settings.__dict__, "send_missed_reminders": False})

        process_due_reminders(mem_conn, client, today=today, settings=settings)

        # No offset matches today exactly for this check
        assert len(client.calls) == 0

    def test_sends_only_today_exact(self, mem_conn, default_settings):
        """Exactly one send when today matches one offset exactly."""
        today = date(2025, 6, 1)
        # Set due date so 3-day offset lands on today
        due = today + timedelta(days=3)
        add_check(mem_conn, title="Exact 3", due_date=due.isoformat(), phone_number="+989121234567")
        client = RecordingSmsClient()
        settings = Settings(**{**default_settings.__dict__, "send_missed_reminders": False})

        process_due_reminders(mem_conn, client, today=today, settings=settings)

        assert len(client.calls) == 1
        assert "3 روز مانده" in client.calls[0]["body"]


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------

class TestFailureHandling:
    def test_failed_send_logged_as_failed(self, mem_conn, default_settings):
        """When SMS fails, reminder_log is written with status='failed'."""
        today = date(2025, 6, 1)
        due = today + timedelta(days=3)
        phone = "+989121234567"
        add_check(mem_conn, title="Fail Check", due_date=due.isoformat(), phone_number=phone)

        client = RecordingSmsClient()
        client._fail_on = phone
        settings = Settings(**{**default_settings.__dict__, "send_missed_reminders": False})

        process_due_reminders(mem_conn, client, today=today, settings=settings)

        rows = mem_conn.execute("SELECT * FROM reminder_logs").fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "failed"
        assert rows[0]["error"] is not None

    def test_failed_send_retried_next_run(self, mem_conn, default_settings):
        """A failed reminder is retried (and can succeed) on the next run."""
        today = date(2025, 6, 1)
        # Use a due date where only the 3-day offset matches today exactly,
        # to keep the test focused on a single retry.
        due = today + timedelta(days=3)
        phone = "+989121234567"
        add_check(mem_conn, title="Retry Check", due_date=due.isoformat(), phone_number=phone)
        settings = Settings(**{**default_settings.__dict__, "send_missed_reminders": False})

        # First run: fail
        failing_client = RecordingSmsClient()
        failing_client._fail_on = phone
        process_due_reminders(mem_conn, failing_client, today=today, settings=settings)

        rows = mem_conn.execute("SELECT status FROM reminder_logs").fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "failed"

        # Second run (same day, send_missed=False retries only the failed 3-day reminder)
        success_client = RecordingSmsClient()
        process_due_reminders(mem_conn, success_client, today=today, settings=settings)

        rows = mem_conn.execute("SELECT status FROM reminder_logs").fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "sent"
        assert len(success_client.calls) == 1


# ---------------------------------------------------------------------------
# list_due_reminders unit tests
# ---------------------------------------------------------------------------

class TestListDueReminders:
    def test_returns_empty_when_no_checks(self, mem_conn):
        result = list_due_reminders(mem_conn, today=date(2025, 6, 1))
        assert result == []

    def test_inactive_check_excluded(self, mem_conn):
        check_id = add_check(mem_conn, title="Inactive", due_date="2025-06-04", phone_number="+1")
        mem_conn.execute("UPDATE checks SET active=0 WHERE id=?", (check_id,))
        mem_conn.commit()
        result = list_due_reminders(mem_conn, today=date(2025, 6, 1), send_missed=False)
        assert result == []
