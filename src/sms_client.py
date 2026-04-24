"""
SMS client abstraction for CheckReminder.

Provides a base class and two implementations:
  - MockSmsClient  – no-op, prints to stdout; safe for development/testing.
  - TwilioSmsClient – sends real SMS via Twilio REST API.

Usage
-----
    client = build_sms_client(settings)
    msg_id = client.send_sms("+989121234567", "Your check is due in 3 days.")
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from .config import Settings

logger = logging.getLogger(__name__)


class SmsClientBase(ABC):
    """Abstract SMS client interface."""

    @abstractmethod
    def send_sms(self, to_number: str, body: str) -> Optional[str]:
        """
        Send an SMS and return a provider message ID (or None for mock).

        Raises :class:`SmsDeliveryError` on failure.
        """


class SmsDeliveryError(Exception):
    """Raised when an SMS could not be delivered."""


# ---------------------------------------------------------------------------
# Mock implementation
# ---------------------------------------------------------------------------

class MockSmsClient(SmsClientBase):
    """No-op SMS client — logs messages instead of sending them."""

    def send_sms(self, to_number: str, body: str) -> Optional[str]:
        masked = _mask_phone(to_number)
        logger.info("[MockSMS] To: %s | %s", masked, body)
        print(f"[MockSMS] To: {masked} | {body}")
        return "mock-msg-id"


# ---------------------------------------------------------------------------
# Twilio implementation
# ---------------------------------------------------------------------------

class TwilioSmsClient(SmsClientBase):
    """Send SMS via Twilio REST API."""

    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        try:
            from twilio.rest import Client  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "twilio package is required for TwilioSmsClient. "
                "Install it with: pip install twilio"
            ) from exc

        self._client = Client(account_sid, auth_token)
        self._from_number = from_number

    def send_sms(self, to_number: str, body: str) -> Optional[str]:
        masked = _mask_phone(to_number)
        try:
            message = self._client.messages.create(
                body=body,
                from_=self._from_number,
                to=to_number,
            )
            logger.info("SMS sent to %s — SID: %s", masked, message.sid)
            return message.sid
        except Exception as exc:
            logger.error("Failed to send SMS to %s: %s", masked, exc)
            raise SmsDeliveryError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_sms_client(settings: Settings) -> SmsClientBase:
    """Return the appropriate SMS client based on ``settings.sms_provider``."""
    if settings.sms_provider == "twilio":
        return TwilioSmsClient(
            account_sid=settings.twilio_account_sid or "",
            auth_token=settings.twilio_auth_token or "",
            from_number=settings.twilio_from_number or "",
        )
    return MockSmsClient()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask_phone(number: str) -> str:
    """Return a partially masked phone number for safe logging."""
    if len(number) <= 4:
        return "****"
    return number[:3] + "****" + number[-2:]
