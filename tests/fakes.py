"""Test doubles shared across the suite.

Every fake is queue backed so a test can either pre-seed a whole conversation or push
messages one at a time and assert on what happened in between. The second mode is what the
barge in tests need.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from arcagent.speech.cartesia_tts import TtsSocketClosed
from arcagent.speech.deepgram_stt import SttSocketClosed
from arcagent.telephony.session_handler import SocketClosed

STREAM_SID = "MZ0000000000000000000000000000test"
CALL_SID = "CA0000000000000000000000000000test"
ACCOUNT_SID = "AC0000000000000000000000000000test"

_HANGUP = object()


class FakeMediaSocket:
    """A scripted Twilio WebSocket.

    With ``keep_open`` false, which is the default, the socket raises
    :class:`SocketClosed` once the inbox is drained. That models a call that hung up and
    keeps the simple tests short. With ``keep_open`` true it blocks instead, and the test
    drives the call by calling :meth:`push` and finally :meth:`hangup`.
    """

    def __init__(self, inbox: list[dict[str, Any]] | None = None, keep_open: bool = False) -> None:
        self.keep_open = keep_open
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        for message in inbox or []:
            self._queue.put_nowait(message)

    def push(self, message: dict[str, Any]) -> None:
        self._queue.put_nowait(message)

    def hangup(self) -> None:
        self._queue.put_nowait(_HANGUP)

    async def receive_json(self) -> dict[str, Any]:
        if not self.keep_open and self._queue.empty():
            self.closed = True
            raise SocketClosed
        message = await self._queue.get()
        if message is _HANGUP:
            self.closed = True
            raise SocketClosed
        return message

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)

    def sent_of(self, event: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m.get("event") == event]

    def sent_media_payloads(self) -> list[bytes]:
        return [base64.b64decode(m["media"]["payload"]) for m in self.sent_of("media")]

    @property
    def media_count(self) -> int:
        return len(self.sent_of("media"))


# --------------------------------------------------------------- Twilio messages


def connected_message() -> dict[str, Any]:
    return {"event": "connected", "protocol": "Call", "version": "1.0.0"}


def start_message(stream_sid: str = STREAM_SID, call_sid: str = CALL_SID) -> dict[str, Any]:
    return {
        "event": "start",
        "sequenceNumber": "1",
        "streamSid": stream_sid,
        "start": {
            "streamSid": stream_sid,
            "accountSid": ACCOUNT_SID,
            "callSid": call_sid,
            "tracks": ["inbound"],
            "customParameters": {},
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
        },
    }


def media_message(
    payload: bytes,
    stream_sid: str = STREAM_SID,
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


def mark_message(name: str, stream_sid: str = STREAM_SID) -> dict[str, Any]:
    return {"event": "mark", "streamSid": stream_sid, "mark": {"name": name}}


def dtmf_message(digit: str, stream_sid: str = STREAM_SID) -> dict[str, Any]:
    return {
        "event": "dtmf",
        "streamSid": stream_sid,
        "dtmf": {"track": "inbound_track", "digit": digit},
    }


def stop_message(stream_sid: str = STREAM_SID, call_sid: str = CALL_SID) -> dict[str, Any]:
    return {
        "event": "stop",
        "streamSid": stream_sid,
        "stop": {"accountSid": ACCOUNT_SID, "callSid": call_sid},
    }


# ------------------------------------------------------------------- Deepgram


class FakeSttSocket:
    """A scripted Deepgram socket.

    Items in ``script`` are delivered by ``recv`` in order; an exception instance is raised
    rather than returned, which is how a mid call disconnect is simulated. ``push`` adds
    more at any time. When nothing is queued ``recv`` blocks, like a real idle socket.
    """

    def __init__(self, script: list[Any] | None = None) -> None:
        self.sent: list[Any] = []
        self.closed = False
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        for item in script or []:
            self._queue.put_nowait(item)

    def push(self, raw: str) -> None:
        self._queue.put_nowait(raw)

    async def send(self, data: Any) -> None:
        if self.closed:
            raise SttSocketClosed
        self.sent.append(data)

    async def recv(self) -> Any:
        item = await self._queue.get()
        if isinstance(item, Exception):
            raise item
        return item

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


# -------------------------------------------------------------------- Cartesia


class FakeTtsSocket:
    """A scripted Cartesia socket.

    In ``auto`` mode each synthesis request is answered from ``responses`` and completed
    immediately, which is what most tests want. With ``auto`` false the request is recorded
    and nothing comes back until the test calls :meth:`push_chunk` and :meth:`push_done`,
    which is what a barge in test needs to interrupt a half spoken utterance.
    """

    def __init__(self, responses: list[list[bytes]] | None = None, auto: bool = True) -> None:
        self.responses: list[list[bytes]] = list(responses or [])
        self.auto = auto
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, data: Any) -> None:
        if self.closed:
            raise TtsSocketClosed
        message = json.loads(data)
        self.sent.append(message)
        if message.get("cancel") or not self.auto:
            return
        context_id = message["context_id"]
        for piece in self.responses.pop(0) if self.responses else [b"\xff" * 320]:
            self.push_chunk(context_id, piece)
        self.push_done(context_id)

    async def recv(self) -> str:
        return await self._queue.get()

    async def close(self) -> None:
        self.closed = True

    def push_chunk(self, context_id: str, audio: bytes) -> None:
        self._queue.put_nowait(
            json.dumps(
                {
                    "type": "chunk",
                    "context_id": context_id,
                    "data": base64.b64encode(audio).decode("ascii"),
                    "done": False,
                }
            )
        )

    def push_done(self, context_id: str) -> None:
        self._queue.put_nowait(json.dumps({"type": "done", "context_id": context_id}))

    def push(self, message: dict[str, Any]) -> None:
        self._queue.put_nowait(json.dumps(message))

    @property
    def requests(self) -> list[dict[str, Any]]:
        return [m for m in self.sent if "transcript" in m]

    @property
    def cancels(self) -> list[str]:
        return [m["context_id"] for m in self.sent if m.get("cancel")]
