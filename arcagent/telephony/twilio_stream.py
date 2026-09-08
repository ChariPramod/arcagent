"""Twilio Media Streams frame parsing and message construction.

Wire format, per docs/vendor_params.md section 1: base64 encoded mulaw, 8000 Hz, mono,
20 ms per frame. One :class:`StreamSession` per WebSocket connection.

This module is pure: it parses dicts into events and builds dicts to send. It owns no
sockets and no tasks, which is what makes it testable without a call.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# mulaw is one byte per sample. 8000 Hz * 0.020 s = 160 samples = 160 bytes.
SAMPLE_RATE_HZ = 8000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE_HZ * FRAME_MS // 1000
MULAW_SILENCE = 0xFF  # mulaw encodes silence as 0xFF, not 0x00


class TwilioEventType(StrEnum):
    CONNECTED = "connected"
    START = "start"
    MEDIA = "media"
    DTMF = "dtmf"
    MARK = "mark"
    STOP = "stop"


class TwilioFrameError(ValueError):
    """Raised when a Twilio message cannot be parsed into a known event."""


@dataclass(frozen=True, slots=True)
class ConnectedEvent:
    protocol: str
    version: str


@dataclass(frozen=True, slots=True)
class StartEvent:
    stream_sid: str
    call_sid: str
    account_sid: str
    tracks: tuple[str, ...]
    encoding: str
    sample_rate: int
    channels: int
    custom_parameters: dict[str, str]


@dataclass(frozen=True, slots=True)
class MediaEvent:
    stream_sid: str
    track: str
    chunk: int
    timestamp_ms: int
    payload: bytes
    """Decoded mulaw bytes. Never re-encoded or resampled."""


@dataclass(frozen=True, slots=True)
class DtmfEvent:
    stream_sid: str
    digit: str
    track: str


@dataclass(frozen=True, slots=True)
class MarkEvent:
    stream_sid: str
    name: str


@dataclass(frozen=True, slots=True)
class StopEvent:
    stream_sid: str
    call_sid: str
    account_sid: str


TwilioEvent = ConnectedEvent | StartEvent | MediaEvent | DtmfEvent | MarkEvent | StopEvent


def parse_event(message: dict[str, Any]) -> TwilioEvent:
    """Parse one decoded Twilio WebSocket message into a typed event.

    Raises:
        TwilioFrameError: the message has no ``event`` key, an unknown event type,
            or is missing a field the event type requires.
    """
    try:
        raw_event = message["event"]
    except (KeyError, TypeError) as exc:
        raise TwilioFrameError(f"message has no event key: {message!r}") from exc

    try:
        event_type = TwilioEventType(raw_event)
    except ValueError as exc:
        raise TwilioFrameError(f"unknown event type: {raw_event!r}") from exc

    try:
        return _PARSERS[event_type](message)
    except TwilioFrameError:
        raise
    except (KeyError, TypeError, ValueError, base64.binascii.Error) as exc:
        raise TwilioFrameError(f"malformed {event_type} message: {exc}") from exc


def _parse_connected(m: dict[str, Any]) -> ConnectedEvent:
    return ConnectedEvent(protocol=m["protocol"], version=m["version"])


def _parse_start(m: dict[str, Any]) -> StartEvent:
    start = m["start"]
    media_format = start.get("mediaFormat", {})
    return StartEvent(
        stream_sid=start.get("streamSid") or m["streamSid"],
        call_sid=start["callSid"],
        account_sid=start.get("accountSid", ""),
        tracks=tuple(start.get("tracks", ())),
        encoding=media_format.get("encoding", ""),
        sample_rate=int(media_format.get("sampleRate", 0)),
        channels=int(media_format.get("channels", 0)),
        custom_parameters=dict(start.get("customParameters") or {}),
    )


def _parse_media(m: dict[str, Any]) -> MediaEvent:
    media = m["media"]
    return MediaEvent(
        stream_sid=m["streamSid"],
        track=media.get("track", "inbound"),
        chunk=int(media.get("chunk", 0)),
        timestamp_ms=int(media.get("timestamp", 0)),
        payload=base64.b64decode(media["payload"], validate=True),
    )


def _parse_dtmf(m: dict[str, Any]) -> DtmfEvent:
    dtmf = m["dtmf"]
    return DtmfEvent(
        stream_sid=m["streamSid"],
        digit=dtmf["digit"],
        track=dtmf.get("track", ""),
    )


def _parse_mark(m: dict[str, Any]) -> MarkEvent:
    return MarkEvent(stream_sid=m["streamSid"], name=m["mark"]["name"])


def _parse_stop(m: dict[str, Any]) -> StopEvent:
    stop = m.get("stop", {})
    return StopEvent(
        stream_sid=m["streamSid"],
        call_sid=stop.get("callSid", ""),
        account_sid=stop.get("accountSid", ""),
    )


_PARSERS = {
    TwilioEventType.CONNECTED: _parse_connected,
    TwilioEventType.START: _parse_start,
    TwilioEventType.MEDIA: _parse_media,
    TwilioEventType.DTMF: _parse_dtmf,
    TwilioEventType.MARK: _parse_mark,
    TwilioEventType.STOP: _parse_stop,
}


def build_media_message(stream_sid: str, payload: bytes) -> dict[str, Any]:
    """Outbound audio frame. ``payload`` is raw mulaw, base64 encoded here and nowhere else."""
    return {
        "event": "media",
        "streamSid": stream_sid,
        "media": {"payload": base64.b64encode(payload).decode("ascii")},
    }


def build_mark_message(stream_sid: str, name: str) -> dict[str, Any]:
    """Playback checkpoint. Twilio echoes a ``mark`` event back once this point is played."""
    return {"event": "mark", "streamSid": stream_sid, "mark": {"name": name}}


def build_clear_message(stream_sid: str) -> dict[str, Any]:
    """Discard audio Twilio has buffered but not yet played. This is barge in."""
    return {"event": "clear", "streamSid": stream_sid}


def chunk_audio(audio: bytes, frame_bytes: int = FRAME_BYTES, pad: bool = True) -> list[bytes]:
    """Split raw mulaw into 20 ms Twilio frames.

    A trailing partial frame is padded with mulaw silence when ``pad`` is true, so every
    frame Twilio receives is exactly ``frame_bytes`` long. With ``pad`` false the partial
    frame is returned as is, which is what a streaming caller wants when more audio for the
    same utterance is still arriving.
    """
    if frame_bytes <= 0:
        raise ValueError("frame_bytes must be positive")
    frames = [audio[i : i + frame_bytes] for i in range(0, len(audio), frame_bytes)]
    if frames and pad and len(frames[-1]) < frame_bytes:
        frames[-1] = frames[-1].ljust(frame_bytes, bytes([MULAW_SILENCE]))
    return frames


@dataclass(slots=True)
class StreamSession:
    """Per connection state for one Twilio media stream.

    Holds the identifiers the rest of the pipeline needs and counts frames both ways so a
    call can be reconciled against Twilio's own numbers afterwards.
    """

    stream_sid: str = ""
    call_sid: str = ""
    account_sid: str = ""
    encoding: str = ""
    sample_rate: int = 0
    custom_parameters: dict[str, str] = field(default_factory=dict)
    started: bool = False
    stopped: bool = False
    inbound_frames: int = 0
    outbound_frames: int = 0
    pending_marks: list[str] = field(default_factory=list)

    def on_start(self, event: StartEvent) -> None:
        self.stream_sid = event.stream_sid
        self.call_sid = event.call_sid
        self.account_sid = event.account_sid
        self.encoding = event.encoding
        self.sample_rate = event.sample_rate
        self.custom_parameters = dict(event.custom_parameters)
        self.started = True

    def on_media(self, event: MediaEvent) -> None:
        self.inbound_frames += 1

    def on_mark(self, event: MarkEvent) -> None:
        """Twilio finished playing up to this mark. Drop it and everything queued before it."""
        if event.name in self.pending_marks:
            index = self.pending_marks.index(event.name)
            del self.pending_marks[: index + 1]

    def on_stop(self, event: StopEvent) -> None:
        self.stopped = True

    def note_sent_mark(self, name: str) -> None:
        self.pending_marks.append(name)

    def note_sent_frames(self, count: int) -> None:
        self.outbound_frames += count

    def clear_pending_marks(self) -> None:
        """Called alongside a ``clear`` message. Nothing queued will be played now."""
        self.pending_marks.clear()

    @property
    def is_playing(self) -> bool:
        """True while Twilio still has un-played audio we sent."""
        return bool(self.pending_marks)
