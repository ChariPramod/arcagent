"""A fake Twilio Media Streams client.

Speaks the Twilio side of the protocol against the isolated ``/eval/voice/stream`` handler, so
tier 2 exercises the actual WebSocket code path, the actual STT, and the actual barge in
logic. Only the phone network is missing.

It is deliberately not a mock of our own session: mocking that would test nothing that
tier 1 does not already test.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from arcagent.logging import get_logger
from arcagent.telephony.twilio_stream import FRAME_BYTES, FRAME_MS, chunk_audio

log = get_logger(__name__)

REAL_TIME_FRAME_S = FRAME_MS / 1000


@dataclass
class ReceivedAudio:
    """Agent audio the fake Twilio collected, per utterance."""

    frames: list[bytes] = field(default_factory=list)
    first_frame_at: float | None = None
    mark_at: float | None = None
    mark_name: str | None = None

    @property
    def duration_s(self) -> float:
        return len(self.frames) * REAL_TIME_FRAME_S


@dataclass
class ReceivedReply:
    """A whole logical evaluation reply, delivered and acknowledged before completion."""

    frames: list[bytes]
    texts: list[str]
    terminal: bool


class FakeTwilioCall:
    """One call, over a real WebSocket, against a running server.

    Usage::

        async with FakeTwilioCall(url, call_sid, from_number) as call:
            await call.start()
            await call.play(mulaw_audio)
            reply = await call.wait_for_reply()
    """

    def __init__(
        self,
        url: str,
        call_sid: str | None = None,
        from_number: str = "+15550000000",
        realtime: bool = True,
        auth_token: str = "",
    ) -> None:
        if auth_token:
            validate_eval_url(url)
        self.auth_token = auth_token
        self.url = url
        self.call_sid = call_sid or f"CA{uuid.uuid4().hex}"
        self.stream_sid = f"MZ{uuid.uuid4().hex}"
        self.from_number = from_number
        self.realtime = realtime
        self.socket: Any = None
        self.frames_sent = 0
        self.cleared = 0
        self._reader: asyncio.Task[None] | None = None
        self._inbox: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def __aenter__(self) -> FakeTwilioCall:
        import websockets

        validate_eval_url(self.url)
        if not self.auth_token:
            raise ValueError("An audio evaluation token is required")
        self.socket = await websockets.connect(
            self.url, additional_headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        self._reader = asyncio.create_task(self._read_loop(), name="fake-twilio-reader")
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.hangup()

    async def _read_loop(self) -> None:
        try:
            async for raw in self.socket:
                try:
                    self._inbox.put_nowait(json.loads(raw))
                except json.JSONDecodeError:
                    log.warning("fake_twilio_unparsed_message")
        except Exception:
            pass
        finally:
            self._inbox.put_nowait(None)

    async def _send(self, message: dict[str, Any]) -> None:
        await self.socket.send(json.dumps(message))

    async def start(self) -> None:
        """The connected and start events, carrying the call sid the app expects."""
        await self._send({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        await self._send(
            {
                "event": "start",
                "sequenceNumber": "1",
                "streamSid": self.stream_sid,
                "start": {
                    "streamSid": self.stream_sid,
                    "accountSid": "ACeval",
                    "callSid": self.call_sid,
                    "tracks": ["inbound"],
                    "customParameters": {
                        "call_sid": self.call_sid,
                        "from": self.from_number,
                    },
                    "mediaFormat": {
                        "encoding": "audio/x-mulaw",
                        "sampleRate": 8000,
                        "channels": 1,
                    },
                },
            }
        )

    async def play(self, mulaw: bytes) -> None:
        """Stream raw mulaw in as 20 ms frames.

        Paced in real time by default. Sending a whole utterance instantly would let
        Deepgram's endpointer see the entire turn at once, which is not what a phone call
        looks like and would make the measured latency meaningless.
        """
        for frame in chunk_audio(mulaw):
            await self._send(
                {
                    "event": "media",
                    "streamSid": self.stream_sid,
                    "media": {
                        "track": "inbound",
                        "chunk": str(self.frames_sent),
                        "timestamp": str(self.frames_sent * FRAME_MS),
                        "payload": base64.b64encode(frame).decode("ascii"),
                    },
                }
            )
            self.frames_sent += 1
            if self.realtime:
                await asyncio.sleep(REAL_TIME_FRAME_S)

    async def play_silence(self, seconds: float) -> None:
        """Silence is what a caller listening sounds like, and the agent needs to hear it."""
        await self.play(bytes([0xFF]) * int(8000 * seconds))

    async def wait_for_agent(self, wait_s: float = 20.0) -> ReceivedAudio:
        """Collect one marked utterance. A mark does not delimit the entire logical reply.

        Named ``wait_s`` rather than ``timeout`` deliberately: a caller reaching for
        ``asyncio.timeout`` around this would cancel mid utterance and lose the frames
        already collected, which is exactly the measurement tier 2 exists to take.
        """
        received = ReceivedAudio()
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            try:
                message = await asyncio.wait_for(
                    self._inbox.get(), timeout=max(0.05, deadline - time.monotonic())
                )
            except TimeoutError:
                break

            if message is None:
                break
            match message.get("event"):
                case "media":
                    if received.first_frame_at is None:
                        received.first_frame_at = time.monotonic()
                    received.frames.append(base64.b64decode(message["media"]["payload"]))
                case "clear":
                    # Barge in. Everything collected so far was discarded by Twilio.
                    self.cleared += 1
                    received = ReceivedAudio()
                case "mark":
                    received.mark_at = time.monotonic()
                    received.mark_name = message["mark"]["name"]
                    await self._send(
                        {
                            "event": "mark",
                            "streamSid": self.stream_sid,
                            "mark": {"name": received.mark_name},
                        }
                    )
                    return received
        return received

    async def wait_for_reply(self, wait_s: float = 20.0) -> ReceivedReply:
        """Acknowledge utterances immediately; wait for the server's logical boundary.

        Evaluation-only completion metadata is emitted after server persistence. Marks
        still acknowledge synthetic delivery, not real telephone playback duration.
        """
        frames: list[bytes] = []
        pending_frames = 0
        acknowledged = 0
        seen_marks: set[str] = set()
        async with asyncio.timeout(wait_s):
            while True:
                message = await self._inbox.get()
                if message is None:
                    raise ConnectionError("Evaluation stream closed before reply completion")
                if not isinstance(message, dict):
                    raise ValueError("Invalid evaluation stream event")
                match message.get("event"):
                    case "media":
                        audio = base64.b64decode(message["media"]["payload"], validate=True)
                        if not audio:
                            raise ValueError("Empty evaluation audio frame")
                        frames.append(audio)
                        pending_frames += 1
                    case "mark":
                        name = message["mark"]["name"]
                        if not isinstance(name, str) or not name:
                            raise ValueError("Invalid evaluation audio mark")
                        await self._send(
                            {
                                "event": "mark",
                                "streamSid": self.stream_sid,
                                "mark": {"name": name},
                            }
                        )
                        if name not in seen_marks and pending_frames:
                            acknowledged += 1
                            pending_frames = 0
                        seen_marks.add(name)
                    case "clear":
                        self.cleared += 1
                        frames = []
                        pending_frames = 0
                        acknowledged = 0
                    case "eval.reply_complete":
                        reply = message.get("reply")
                        if not isinstance(reply, dict):
                            raise ValueError("Invalid evaluation reply completion")
                        texts = reply.get("texts")
                        terminal = reply.get("terminal")
                        if (
                            not isinstance(texts, list)
                            or not texts
                            or any(not isinstance(text, str) or not text.strip() for text in texts)
                            or type(terminal) is not bool
                            or not frames
                            or pending_frames
                            or acknowledged != len(texts)
                        ):
                            raise ValueError("Invalid evaluation reply completion")
                        return ReceivedReply(frames, texts, terminal)

    async def stream_events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            message = await self._inbox.get()
            if message is None:
                return
            yield message

    async def hangup(self) -> None:
        try:
            await self._send(
                {
                    "event": "stop",
                    "streamSid": self.stream_sid,
                    "stop": {"accountSid": "ACeval", "callSid": self.call_sid},
                }
            )
        except Exception:
            pass
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except asyncio.CancelledError:
                pass
        if self.socket is not None:
            try:
                await self.socket.close()
            except Exception:
                pass


def mulaw_duration_s(audio: bytes) -> float:
    """How long a stretch of mulaw takes to play. One byte is one sample at 8 kHz."""
    return len(audio) / 8000


def frame_count(audio: bytes) -> int:
    return (len(audio) + FRAME_BYTES - 1) // FRAME_BYTES


def validate_eval_url(url: str) -> None:
    """Never direct the synthetic caller to a production voice route or leak its token."""
    parsed = urlsplit(url)
    secure = parsed.scheme == "wss" or (
        parsed.scheme == "ws" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    )
    if (
        not secure
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != "/eval/voice/stream"
    ):
        raise ValueError("Use a secure isolated audio evaluation endpoint")
