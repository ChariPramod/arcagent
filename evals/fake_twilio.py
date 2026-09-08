"""A fake Twilio Media Streams client.

Speaks the Twilio side of the protocol against the real ``/voice/stream`` handler, so
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


class FakeTwilioCall:
    """One call, over a real WebSocket, against a running server.

    Usage::

        async with FakeTwilioCall(url, call_sid, from_number) as call:
            await call.start()
            await call.play(mulaw_audio)
            audio = await call.wait_for_agent()
    """

    def __init__(
        self,
        url: str,
        call_sid: str | None = None,
        from_number: str = "+15550000000",
        realtime: bool = True,
    ) -> None:
        self.url = url
        self.call_sid = call_sid or f"CA{uuid.uuid4().hex}"
        self.stream_sid = f"MZ{uuid.uuid4().hex}"
        self.from_number = from_number
        self.realtime = realtime
        self.socket: Any = None
        self.frames_sent = 0
        self.cleared = 0
        self._reader: asyncio.Task[None] | None = None
        self._inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def __aenter__(self) -> FakeTwilioCall:
        import websockets

        self.socket = await websockets.connect(self.url)
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
        """Collect agent audio until its mark arrives, which means it finished speaking.

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

    async def stream_events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            yield await self._inbox.get()

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
