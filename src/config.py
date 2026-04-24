"""
Configuration loading and validation for CheckReminder.

Reads settings from environment variables (supports .env via python-dotenv).
"""

import os
from dataclasses import dataclass, field
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional; env vars may already be set


@dataclass
class Settings:
    twilio_account_sid: Optional[str]
    twilio_auth_token: Optional[str]
    twilio_from_number: Optional[str]
    timezone: str
    sms_provider: str
    db_path: str
    send_missed_reminders: bool
    reminder_offsets: list = field(default_factory=lambda: [10, 3, 1])


def load_settings() -> Settings:
    """Read all configuration from environment variables with sensible defaults."""
    send_missed_raw = os.environ.get("SEND_MISSED_REMINDERS", "true").strip().lower()
    send_missed = send_missed_raw in ("1", "true", "yes")

    return Settings(
        twilio_account_sid=os.environ.get("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=os.environ.get("TWILIO_AUTH_TOKEN"),
        twilio_from_number=os.environ.get("TWILIO_FROM_NUMBER"),
        timezone=os.environ.get("TIMEZONE", "Asia/Tehran"),
        sms_provider=os.environ.get("SMS_PROVIDER", "mock").strip().lower(),
        db_path=os.environ.get("DB_PATH", "checkreminder.db"),
        send_missed_reminders=send_missed,
    )


def validate_settings(settings: Settings) -> None:
    """
    Raise ValueError if required settings are missing or invalid.

    Only validates Twilio credentials when sms_provider is 'twilio'.
    """
    if not settings.timezone:
        raise ValueError("TIMEZONE must not be empty.")

    # Verify the timezone string is recognised by the stdlib zoneinfo module.
    try:
        import zoneinfo
        zoneinfo.ZoneInfo(settings.timezone)
    except (ImportError, KeyError):
        # zoneinfo not available (Python < 3.9) or unknown tz — try pytz fallback.
        try:
            import pytz  # type: ignore[import-untyped]
            pytz.timezone(settings.timezone)
        except Exception:
            raise ValueError(f"Unknown timezone: {settings.timezone!r}")

    if settings.sms_provider not in ("twilio", "mock"):
        raise ValueError(
            f"SMS_PROVIDER must be 'twilio' or 'mock', got: {settings.sms_provider!r}"
        )

    if settings.sms_provider == "twilio":
        missing = []
        if not settings.twilio_account_sid:
            missing.append("TWILIO_ACCOUNT_SID")
        if not settings.twilio_auth_token:
            missing.append("TWILIO_AUTH_TOKEN")
        if not settings.twilio_from_number:
            missing.append("TWILIO_FROM_NUMBER")
        if missing:
            raise ValueError(
                f"Twilio provider requires these env vars: {', '.join(missing)}"
            )
