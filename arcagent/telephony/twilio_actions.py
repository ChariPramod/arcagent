"""Twilio REST side effects: warm transfer and the callback SMS.

Both are wrapped so the rest of the app never touches the Twilio client directly, and so
the tests can assert on the exact TwiML and the exact message body without a network call.

Compliance notes that are not optional:
  - the SMS carries opt out language, because it is a transactional message the caller
    asked for and the defensible position still includes the line (docs/compliance_design.md)
  - the message never contains the caller's name or anything about the procedure. A text
    message is read on a lock screen by whoever is holding the phone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from arcagent.config import Settings
from arcagent.logging import get_logger, mask_number
from arcagent.telephony.twiml import dial_coordinator

log = get_logger(__name__)

OPT_OUT_LINE = "Reply STOP to opt out."


class TwilioClient(Protocol):
    """The slice of the Twilio REST client this module uses."""

    @property
    def calls(self) -> Any: ...

    @property
    def messages(self) -> Any: ...


class TransferFailed(RuntimeError):
    """The live call could not be updated. The caller is still on the line."""


class SmsFailed(RuntimeError):
    """The confirmation message could not be sent. The callback is still booked."""


@dataclass(frozen=True, slots=True)
class SmsReceipt:
    sid: str
    status: str


def format_slot(slot_start: datetime) -> str:
    """A slot time a person can read out loud. No leading zero on the hour."""
    hour = slot_start.strftime("%I").lstrip("0") or "12"
    meridiem = slot_start.strftime("%p").lower()
    return f"{slot_start.strftime('%A %B')} {slot_start.day}, {hour}{meridiem}"


def callback_message(slot_start: datetime, practice_name: str = "the office") -> str:
    """The confirmation body.

    Deliberately says nothing about implants, surgery, or the caller's name. It confirms a
    call back at a time, and that is all a lock screen needs to show.
    """
    return (
        f"You are booked for a call back from {practice_name} on {format_slot(slot_start)}. "
        f"{OPT_OUT_LINE}"
    )


class TwilioActions:
    """Warm transfer and SMS, against an injected client."""

    def __init__(self, settings: Settings, client: TwilioClient | None = None) -> None:
        self._settings = settings
        self._client = client

    def _get_client(self) -> TwilioClient:
        if self._client is None:
            from twilio.rest import Client

            self._client = Client(
                self._settings.twilio_account_sid, self._settings.twilio_auth_token
            )
        return self._client

    def warm_transfer(self, call_sid: str, coordinator_number: str | None = None) -> str:
        """Replace the live call's TwiML with a dial to the coordinator.

        Call this only after the handoff line has been spoken and its mark acknowledged.
        Updating the call tears the media stream down, so anything still queued is lost.

        Raises:
            TransferFailed: the number is not configured, or Twilio rejected the update.
        """
        number = coordinator_number or self._settings.coordinator_number
        if not number:
            raise TransferFailed("COORDINATOR_NUMBER is not configured")

        twiml = dial_coordinator(number)
        try:
            self._get_client().calls(call_sid).update(twiml=twiml)
        except Exception as exc:
            log.exception("warm_transfer_failed", call_sid=call_sid)
            raise TransferFailed(str(exc)) from exc

        log.info("warm_transfer", call_sid=call_sid, coordinator_number=mask_number(number))
        return twiml

    def send_callback_sms(self, to_number: str, slot_start: datetime) -> SmsReceipt:
        """Send the confirmation. The callback is already booked; this only confirms it.

        Raises:
            SmsFailed: no from number configured, or Twilio rejected the send.
        """
        if not self._settings.twilio_number:
            raise SmsFailed("TWILIO_NUMBER is not configured")

        body = callback_message(slot_start)
        try:
            message = self._get_client().messages.create(
                to=to_number, from_=self._settings.twilio_number, body=body
            )
        except Exception as exc:
            log.exception("callback_sms_failed", to_number=mask_number(to_number))
            raise SmsFailed(str(exc)) from exc

        receipt = SmsReceipt(sid=message.sid, status=getattr(message, "status", "queued"))
        log.info(
            "callback_sms_sent",
            to_number=mask_number(to_number),
            sms_sid=receipt.sid,
            sms_status=receipt.status,
        )
        return receipt
