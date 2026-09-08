"""Deepgram streaming speech to text.

Audio goes in as raw mulaw 8 kHz binary frames, exactly as they arrive from Twilio, with
no resampling. Transcript events come out of an async iterator.

Parameter names come from docs/vendor_params.md section 2. Nothing here is guessed: a
parameter not in that table does not appear in this file.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from arcagent.config import Settings
from arcagent.logging import get_logger

log = get_logger(__name__)

DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"
KEEPALIVE_MESSAGE = {"type": "KeepAlive"}
CLOSE_MESSAGE = {"type": "CloseStream"}

# Deepgram closes an idle socket. Ping well inside that window.
KEEPALIVE_INTERVAL_S = 5.0
RECONNECT_BASE_DELAY_S = 0.25
RECONNECT_MAX_DELAY_S = 8.0


@dataclass(frozen=True, slots=True)
class TranscriptEvent:
    """One transcript from Deepgram, interim or final.

    Attributes:
        text: the transcript for this segment. Empty on a silent interim.
        is_final: Deepgram will not revise this segment.
        speech_final: Deepgram's endpointer thinks the caller stopped talking.
        ts: monotonic clock reading when the event was received, for latency arithmetic.
        start_s: offset of this segment in the audio stream.
        duration_s: length of this segment.
        confidence: Deepgram's confidence for the chosen alternative.
        language: detected language when detect_language is on, otherwise empty.
    """

    text: str
    is_final: bool
    speech_final: bool
    ts: float
    start_s: float = 0.0
    duration_s: float = 0.0
    confidence: float = 0.0
    language: str = ""

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass(frozen=True, slots=True)
class UtteranceEndEvent:
    """Deepgram saw a gap longer than utterance_end_ms. A turn boundary even with no final."""

    last_word_end: float
    ts: float


@dataclass(frozen=True, slots=True)
class SpeechStartedEvent:
    """VAD detected speech. Used to notice a caller talking over the agent."""

    timestamp: float
    ts: float


SttEvent = TranscriptEvent | UtteranceEndEvent | SpeechStartedEvent


class SttSocket(Protocol):
    """The slice of a WebSocket client this module uses."""

    async def send(self, data: str | bytes) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


Connector = Callable[[str, dict[str, str]], Awaitable[SttSocket]]


class SttSocketClosed(Exception):
    """The Deepgram socket went away. The client reconnects and keeps the stream alive."""


def build_stream_url(settings: Settings, language: str | None = None) -> str:
    """Query string for the streaming endpoint, built only from confirmed parameters."""
    params: dict[str, str] = {
        "encoding": "mulaw",
        "sample_rate": "8000",
        "channels": "1",
        "model": "nova-2-phonecall",
        "interim_results": "true",
        "smart_format": "true",
        "vad_events": "true",
        "endpointing": str(settings.deepgram_endpointing_ms),
        "utterance_end_ms": str(settings.deepgram_utterance_end_ms),
    }
    if language:
        params["language"] = language
    return f"{DEEPGRAM_WS_URL}?{urlencode(params)}"


def auth_headers(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Token {settings.deepgram_api_key}"}


def parse_message(raw: str | bytes, ts: float) -> SttEvent | None:
    """Turn one Deepgram message into an event, or None for messages we ignore.

    Ignored: Metadata, and any message type Deepgram adds later. Unknown types are never
    an error, because a vendor adding a message must not break a live call.
    """
    try:
        message: dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        log.warning("deepgram_message_unparsed")
        return None

    match message.get("type"):
        case "Results":
            return _parse_results(message, ts)
        case "UtteranceEnd":
            return UtteranceEndEvent(last_word_end=float(message.get("last_word_end", 0.0)), ts=ts)
        case "SpeechStarted":
            return SpeechStartedEvent(timestamp=float(message.get("timestamp", 0.0)), ts=ts)
        case _:
            return None


def _parse_results(message: dict[str, Any], ts: float) -> TranscriptEvent | None:
    alternatives = message.get("channel", {}).get("alternatives") or []
    if not alternatives:
        return None
    best = alternatives[0]
    return TranscriptEvent(
        text=(best.get("transcript") or "").strip(),
        is_final=bool(message.get("is_final", False)),
        speech_final=bool(message.get("speech_final", False)),
        ts=ts,
        start_s=float(message.get("start", 0.0)),
        duration_s=float(message.get("duration", 0.0)),
        confidence=float(best.get("confidence", 0.0)),
        language=str(message.get("channel", {}).get("detected_language", "")),
    )


class DeepgramSTT:
    """A reconnecting Deepgram streaming session.

    Usage::

        async with DeepgramSTT(settings) as stt:
            await stt.send_audio(mulaw_frame)
            async for event in stt:
                ...

    Audio sent while the socket is down is dropped rather than buffered. Replaying stale
    audio after a reconnect would push every later transcript out of sync with the call.
    """

    def __init__(
        self,
        settings: Settings,
        connect: Connector | None = None,
        language: str | None = None,
        max_reconnects: int = 5,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._connect = connect or _default_connect
        self._language = language
        self._max_reconnects = max_reconnects
        self._clock = clock
        self._sleep = sleep

        self._socket: SttSocket | None = None
        self._events: asyncio.Queue[SttEvent | None] = asyncio.Queue()
        self._reader: asyncio.Task[None] | None = None
        self._keepalive: asyncio.Task[None] | None = None
        self._closing = False
        self.dropped_frames = 0
        self.reconnects = 0

    async def __aenter__(self) -> DeepgramSTT:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def start(self) -> None:
        self._socket = await self._open()
        self._reader = asyncio.create_task(self._read_loop(), name="deepgram-reader")
        self._keepalive = asyncio.create_task(self._keepalive_loop(), name="deepgram-keepalive")

    async def _open(self) -> SttSocket:
        url = build_stream_url(self._settings, self._language)
        socket = await self._connect(url, auth_headers(self._settings))
        log.info("deepgram_connected", endpointing_ms=self._settings.deepgram_endpointing_ms)
        return socket

    async def send_audio(self, frame: bytes) -> None:
        """Forward one mulaw frame. Never raises: a dead socket drops the frame and counts it."""
        if self._socket is None or self._closing:
            self.dropped_frames += 1
            return
        try:
            await self._socket.send(frame)
        except Exception:
            self.dropped_frames += 1

    async def _read_loop(self) -> None:
        attempt = 0
        while not self._closing:
            try:
                assert self._socket is not None
                raw = await self._socket.recv()
            except (SttSocketClosed, ConnectionError, OSError):
                if self._closing:
                    break
                attempt += 1
                if attempt > self._max_reconnects:
                    log.error("deepgram_reconnect_exhausted", attempts=attempt)
                    break
                delay = min(RECONNECT_BASE_DELAY_S * 2 ** (attempt - 1), RECONNECT_MAX_DELAY_S)
                log.warning("deepgram_reconnecting", attempt=attempt, delay_s=delay)
                await self._sleep(delay)
                try:
                    self._socket = await self._open()
                except Exception:
                    continue
                self.reconnects += 1
                # attempt is deliberately not reset here. It resets on the next successful
                # recv, so a socket that reconnects and immediately dies still backs off
                # and still runs out of attempts.
                continue
            except asyncio.CancelledError:
                raise

            attempt = 0
            event = parse_message(raw, self._clock())
            if event is not None:
                self._events.put_nowait(event)

        self._events.put_nowait(None)

    async def _keepalive_loop(self) -> None:
        while not self._closing:
            await self._sleep(KEEPALIVE_INTERVAL_S)
            if self._closing or self._socket is None:
                break
            try:
                await self._socket.send(json.dumps(KEEPALIVE_MESSAGE))
            except Exception:
                pass

    def __aiter__(self) -> AsyncIterator[SttEvent]:
        return self.events()

    async def events(self) -> AsyncIterator[SttEvent]:
        """Yield events until the stream ends."""
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        """Tell Deepgram to finish, then tear down the tasks."""
        if self._closing:
            return
        self._closing = True
        if self._socket is not None:
            try:
                await self._socket.send(json.dumps(CLOSE_MESSAGE))
            except Exception:
                pass
        for task in (self._keepalive, self._reader):
            if task is not None and not task.done():
                task.cancel()
        for task in (self._keepalive, self._reader):
            if task is not None:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        if self._socket is not None:
            try:
                await self._socket.close()
            except Exception:
                pass
        self._events.put_nowait(None)
        log.info("deepgram_closed", dropped_frames=self.dropped_frames, reconnects=self.reconnects)


async def _default_connect(url: str, headers: dict[str, str]) -> SttSocket:
    """Real connector. Imported lazily so tests never need the websockets client."""
    import websockets

    return await websockets.connect(url, additional_headers=headers)  # type: ignore[return-value]
