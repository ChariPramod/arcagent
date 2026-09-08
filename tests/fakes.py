"""Test doubles shared across the suite."""

from __future__ import annotations

import base64
from typing import Any

from arcagent.telephony.session_handler import SocketClosed


class FakeMediaSocket:
    """A scripted Twilio WebSocket.

    ``inbox`` is the sequence of messages the handler will receive. Everything the handler
    sends is appended to ``sent``. Once the inbox is exhausted the socket raises
    :class:`SocketClosed`, which is how a real hung up call presents.
    """

    def __init__(self, inbox: list[dict[str, Any]] | None = None) -> None:
        self.inbox: list[dict[str, Any]] = list(inbox or [])
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def receive_json(self) -> dict[str, Any]:
        if not self.inbox:
            self.closed = True
            raise SocketClosed
        return self.inbox.pop(0)

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)

    def sent_of(self, event: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m.get("event") == event]

    def sent_media_payloads(self) -> list[bytes]:
        return [base64.b64decode(m["media"]["payload"]) for m in self.sent_of("media")]


def connected_message() -> dict[str, Any]:
    return {"event": "connected", "protocol": "Call", "version": "1.0.0"}


def start_message(
    stream_sid: str = "MZ0000000000000000000000000000test",
    call_sid: str = "CA0000000000000000000000000000test",
) -> dict[str, Any]:
    return {
        "event": "start",
        "sequenceNumber": "1",
        "streamSid": stream_sid,
        "start": {
            "streamSid": stream_sid,
            "accountSid": "AC0000000000000000000000000000test",
            "callSid": call_sid,
            "tracks": ["inbound"],
            "customParameters": {},
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
        },
    }


def media_message(
    payload: bytes,
    stream_sid: str = "MZ0000000000000000000000000000test",
    chunk: int = 1,
    timestamp_ms: int = 20,
) -> dict[str, Any]:
    return {
        "event": "media",
        "sequenceNumber": str(chunk + 1),
        "streamSid": stream_sid,
        "media": {
            "track": "inbound",
            "chunk": str(chunk),
            "timestamp": str(timestamp_ms),
            "payload": base64.b64encode(payload).decode("ascii"),
        },
    }


def mark_message(
    name: str, stream_sid: str = "MZ0000000000000000000000000000test"
) -> dict[str, Any]:
    return {"event": "mark", "streamSid": stream_sid, "mark": {"name": name}}


def dtmf_message(
    digit: str, stream_sid: str = "MZ0000000000000000000000000000test"
) -> dict[str, Any]:
    return {
        "event": "dtmf",
        "streamSid": stream_sid,
        "dtmf": {"track": "inbound_track", "digit": digit},
    }


def stop_message(
    stream_sid: str = "MZ0000000000000000000000000000test",
    call_sid: str = "CA0000000000000000000000000000test",
) -> dict[str, Any]:
    return {
        "event": "stop",
        "streamSid": stream_sid,
        "stop": {
            "accountSid": "AC0000000000000000000000000000test",
            "callSid": call_sid,
        },
    }
