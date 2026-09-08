"""Test doubles shared across the suite."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from arcagent.speech.deepgram_stt import SttSocketClosed
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


class FakeSttSocket:
    """A scripted Deepgram socket.

    ``script`` is what ``recv`` returns in order. A :class:`SttSocketClosed` instance in the
    script is raised rather than returned, which is how a mid call disconnect is simulated.
    When the script runs out, ``recv`` blocks forever, matching a live socket with nothing
    to say.
    """

    def __init__(self, script: list[Any] | None = None) -> None:
        self.script: list[Any] = list(script or [])
        self.sent: list[Any] = []
        self.closed = False

    async def send(self, data: Any) -> None:
        if self.closed:
            raise SttSocketClosed
        self.sent.append(data)

    async def recv(self) -> Any:
        while self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        await asyncio.Event().wait()  # never returns
        raise AssertionError("unreachable")

    async def close(self) -> None:
        self.closed = True

    @property
    def audio_frames(self) -> list[bytes]:
        return [d for d in self.sent if isinstance(d, bytes)]

    @property
    def control_messages(self) -> list[dict[str, Any]]:
        return [json.loads(d) for d in self.sent if isinstance(d, str)]


def dg_results(
    transcript: str,
    is_final: bool = False,
    speech_final: bool = False,
    start: float = 0.0,
    duration: float = 0.0,
    confidence: float = 0.98,
    detected_language: str | None = None,
) -> str:
    channel: dict[str, Any] = {
        "alternatives": [{"transcript": transcript, "confidence": confidence}]
    }
    if detected_language is not None:
        channel["detected_language"] = detected_language
    return json.dumps(
        {
            "type": "Results",
            "channel": channel,
            "is_final": is_final,
            "speech_final": speech_final,
            "start": start,
            "duration": duration,
        }
    )


def dg_utterance_end(last_word_end: float = 1.5) -> str:
    return json.dumps({"type": "UtteranceEnd", "last_word_end": last_word_end})


def dg_speech_started(timestamp: float = 0.5) -> str:
    return json.dumps({"type": "SpeechStarted", "timestamp": timestamp})


def dg_metadata() -> str:
    return json.dumps({"type": "Metadata", "request_id": "req_test"})
