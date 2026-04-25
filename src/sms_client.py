"""
SMS client abstraction for CheckReminder.

Provides a base class and three implementations:
    - MockSmsClient  – no-op, prints to stdout; safe for development/testing.
    - TwilioSmsClient – sends real SMS via Twilio REST API.
    - SmsIrSmsClient  – sends SMS via the SMS.ir REST API.

Usage
-----
    client = build_sms_client(settings)
    msg_id = client.send_sms("+989121234567", "Your check is due in 3 days.")
"""

import logging
import json
from abc import ABC, abstractmethod
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
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
        logger.info("[MockSMS] To: %s | %s", _mask_phone(to_number), body)
        print(f"[MockSMS] SMS queued for masked recipient | {body}")
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
        try:
            message = self._client.messages.create(
                body=body,
                from_=self._from_number,
                to=to_number,
            )
            logger.info("SMS sent (SID: %s)", message.sid)
            return message.sid
        except Exception as exc:
            logger.error("Failed to send SMS: %s", exc)
            raise SmsDeliveryError(str(exc)) from exc


# ---------------------------------------------------------------------------
# SMS.ir implementation
# ---------------------------------------------------------------------------

class SmsIrSmsClient(SmsClientBase):
    """Send SMS via the SMS.ir REST API."""

    def __init__(
        self,
        api_key: str,
        line_number: str,
        base_url: str = "https://api.sms.ir/v1",
        username: Optional[str] = None,
        use_legacy_get: bool = False,
    ) -> None:
        self._api_key = api_key.strip()
        self._line_number = line_number.strip()
        self._base_url = base_url.rstrip("/")
        self._username = username.strip() if username else None
        self._use_legacy_get = use_legacy_get

    def send_sms(self, to_number: str, body: str) -> Optional[str]:
        mobile = _normalize_phone_number(to_number)

        if self._use_legacy_get:
            return self._send_sms_legacy_get(mobile, body)

        payload = json.dumps(
            {
                "mobile": mobile,
                "line": self._line_number,
                "text": body,
            }
        ).encode("utf-8")

        request = Request(
            url=f"{self._base_url}/send",
            data=payload,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-API-KEY": self._api_key,
            },
        )

        try:
            with urlopen(request, timeout=30) as response:
                response_body = response.read().decode("utf-8")
                return self._parse_send_response(response_body)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            logger.error("Failed to send SMS.ir message: %s", error_body or exc)
            raise SmsDeliveryError(error_body or str(exc)) from exc
        except URLError as exc:
            logger.error("Failed to reach SMS.ir: %s", exc)
            raise SmsDeliveryError(str(exc)) from exc

    def _send_sms_legacy_get(self, mobile: str, body: str) -> str:
        if not self._username:
            raise SmsDeliveryError("SMSIR_USERNAME is required when SMSIR_USE_LEGACY_GET=true")

        query = urlencode(
            {
                "username": self._username,
                "password": self._api_key,
                "mobile": mobile,
                "line": self._line_number,
                "text": body,
            }
        )

        request = Request(
            url=f"{self._base_url}/send?{query}",
            method="GET",
            headers={
                "Accept": "text/plain",
            },
        )

        try:
            with urlopen(request, timeout=30) as response:
                response_body = response.read().decode("utf-8")
                return self._parse_send_response(response_body)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            logger.error("Failed to send SMS.ir message (legacy GET): %s", error_body or exc)
            raise SmsDeliveryError(error_body or str(exc)) from exc
        except URLError as exc:
            logger.error("Failed to reach SMS.ir (legacy GET): %s", exc)
            raise SmsDeliveryError(str(exc)) from exc

    @staticmethod
    def _parse_send_response(response_body: str) -> str:
        try:
            response = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise SmsDeliveryError("SMS.ir returned invalid JSON") from exc

        if response.get("status") not in (1, "1"):
            message = response.get("message") or "SMS.ir request failed"
            raise SmsDeliveryError(str(message))

        data = response.get("data") or {}
        message_id = data.get("messageId")
        if message_id is None:
            raise SmsDeliveryError("SMS.ir response did not include a messageId")
        return str(message_id)


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
    if settings.sms_provider == "smsir":
        return SmsIrSmsClient(
            api_key=settings.smsir_api_key or "",
            line_number=settings.smsir_line_number or "",
            base_url=settings.smsir_base_url,
            username=settings.smsir_username,
            use_legacy_get=settings.smsir_use_legacy_get,
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


def _normalize_phone_number(number: str) -> str:
    """Return a digits-only phone number for providers that expect canonical numbers."""
    return "".join(ch for ch in number if ch.isdigit())
