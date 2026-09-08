"""Parsing of every Twilio Media Streams event and construction of what we send back."""

from __future__ import annotations

import base64

import pytest

from arcagent.telephony.session_handler import run_echo_session
from arcagent.telephony.twilio_stream import (
    FRAME_BYTES,
    MULAW_SILENCE,
    ConnectedEvent,
    DtmfEvent,
    MarkEvent,
    MediaEvent,
    StartEvent,
    StopEvent,
    StreamSession,
    TwilioFrameError,
    build_clear_message,
    build_mark_message,
    build_media_message,
    chunk_audio,
    parse_event,
)
from tests.fakes import (
    FakeMediaSocket,
    connected_message,
    dtmf_message,
    mark_message,
    media_message,
    start_message,
    stop_message,
)

STREAM_SID = "MZ0000000000000000000000000000test"
CALL_SID = "CA0000000000000000000000000000test"


class TestParsing:
    def test_connected(self) -> None:
        event = parse_event(connected_message())
        assert isinstance(event, ConnectedEvent)
        assert event.protocol == "Call"
        assert event.version == "1.0.0"

    def test_start(self) -> None:
        event = parse_event(start_message())
        assert isinstance(event, StartEvent)
        assert event.stream_sid == STREAM_SID
        assert event.call_sid == CALL_SID
        assert event.tracks == ("inbound",)
        assert event.encoding == "audio/x-mulaw"
        assert event.sample_rate == 8000
        assert event.channels == 1

    def test_start_carries_custom_parameters(self) -> None:
        message = start_message()
        message["start"]["customParameters"] = {"practice_id": "7"}
        event = parse_event(message)
        assert isinstance(event, StartEvent)
        assert event.custom_parameters == {"practice_id": "7"}

    def test_media_payload_is_decoded_not_re_encoded(self) -> None:
        audio = bytes(range(160))
        event = parse_event(media_message(audio, chunk=3, timestamp_ms=60))
        assert isinstance(event, MediaEvent)
        assert event.payload == audio
        assert event.chunk == 3
        assert event.timestamp_ms == 60
        assert event.track == "inbound"

    def test_dtmf(self) -> None:
        event = parse_event(dtmf_message("5"))
        assert isinstance(event, DtmfEvent)
        assert event.digit == "5"

    def test_mark(self) -> None:
        event = parse_event(mark_message("utt-1"))
        assert isinstance(event, MarkEvent)
        assert event.name == "utt-1"

    def test_stop(self) -> None:
        event = parse_event(stop_message())
        assert isinstance(event, StopEvent)
        assert event.call_sid == CALL_SID

    @pytest.mark.parametrize(
        "message",
        [
            {},
            {"foo": "bar"},
            {"event": "nonsense"},
            {"event": "media", "streamSid": STREAM_SID},
            {"event": "media", "streamSid": STREAM_SID, "media": {"payload": "not base64!!"}},
            {"event": "mark", "streamSid": STREAM_SID},
            {"event": "start", "streamSid": STREAM_SID, "start": {}},
        ],
    )
    def test_malformed_messages_raise(self, message: dict) -> None:
        with pytest.raises(TwilioFrameError):
            parse_event(message)


class TestOutboundMessages:
    def test_media_message_round_trips_the_payload(self) -> None:
        audio = bytes([0xFF, 0x7F, 0x00]) * 40
        message = build_media_message(STREAM_SID, audio)
        assert message["event"] == "media"
        assert message["streamSid"] == STREAM_SID
        assert base64.b64decode(message["media"]["payload"]) == audio

    def test_mark_message(self) -> None:
        assert build_mark_message(STREAM_SID, "utt-7") == {
            "event": "mark",
            "streamSid": STREAM_SID,
            "mark": {"name": "utt-7"},
        }

    def test_clear_message_carries_no_payload(self) -> None:
        assert build_clear_message(STREAM_SID) == {"event": "clear", "streamSid": STREAM_SID}


class TestChunking:
    def test_frame_size_is_twenty_milliseconds_of_mulaw(self) -> None:
        assert FRAME_BYTES == 160

    def test_exact_multiple_splits_evenly(self) -> None:
        frames = chunk_audio(b"\x01" * (FRAME_BYTES * 3))
        assert len(frames) == 3
        assert all(len(f) == FRAME_BYTES for f in frames)

    def test_partial_tail_is_padded_with_mulaw_silence(self) -> None:
        frames = chunk_audio(b"\x01" * (FRAME_BYTES + 10))
        assert len(frames) == 2
        assert len(frames[1]) == FRAME_BYTES
        assert frames[1][10:] == bytes([MULAW_SILENCE]) * (FRAME_BYTES - 10)

    def test_unpadded_mode_leaves_the_tail_short(self) -> None:
        frames = chunk_audio(b"\x01" * (FRAME_BYTES + 10), pad=False)
        assert len(frames[1]) == 10

    def test_empty_audio_produces_no_frames(self) -> None:
        assert chunk_audio(b"") == []

    def test_invalid_frame_size_rejected(self) -> None:
        with pytest.raises(ValueError):
            chunk_audio(b"\x01" * 10, frame_bytes=0)


class TestStreamSession:
    def test_start_populates_identifiers(self) -> None:
        session = StreamSession()
        session.on_start(parse_event(start_message()))
        assert session.started
        assert session.call_sid == CALL_SID
        assert session.stream_sid == STREAM_SID

    def test_mark_acknowledgement_drains_the_queue_up_to_that_mark(self) -> None:
        session = StreamSession()
        for name in ("a", "b", "c"):
            session.note_sent_mark(name)
        assert session.is_playing
        session.on_mark(MarkEvent(stream_sid=STREAM_SID, name="b"))
        assert session.pending_marks == ["c"]
        session.on_mark(MarkEvent(stream_sid=STREAM_SID, name="c"))
        assert not session.is_playing

    def test_unknown_mark_is_ignored(self) -> None:
        session = StreamSession()
        session.note_sent_mark("a")
        session.on_mark(MarkEvent(stream_sid=STREAM_SID, name="zzz"))
        assert session.pending_marks == ["a"]

    def test_clear_empties_the_mark_queue(self) -> None:
        session = StreamSession()
        session.note_sent_mark("a")
        session.clear_pending_marks()
        assert not session.is_playing


class TestEchoLoop:
    async def test_every_inbound_frame_comes_back_unchanged(self) -> None:
        payloads = [bytes([i]) * FRAME_BYTES for i in range(1, 4)]
        socket = FakeMediaSocket(
            [
                connected_message(),
                start_message(),
                *[media_message(p, chunk=i) for i, p in enumerate(payloads, start=1)],
                stop_message(),
            ]
        )
        session = await run_echo_session(socket)
        assert socket.sent_media_payloads() == payloads
        assert session.inbound_frames == 3
        assert session.outbound_frames == 3
        assert session.stopped

    async def test_echoed_frames_carry_the_stream_sid_from_start(self) -> None:
        socket = FakeMediaSocket([start_message(), media_message(b"\xff" * FRAME_BYTES)])
        await run_echo_session(socket)
        assert all(m["streamSid"] == STREAM_SID for m in socket.sent_of("media"))

    async def test_unparseable_message_is_skipped_not_fatal(self) -> None:
        socket = FakeMediaSocket(
            [
                start_message(),
                {"event": "garbage"},
                media_message(b"\x02" * FRAME_BYTES),
                stop_message(),
            ]
        )
        session = await run_echo_session(socket)
        assert session.inbound_frames == 1
        assert len(socket.sent_of("media")) == 1

    async def test_socket_closing_without_stop_ends_the_loop(self) -> None:
        socket = FakeMediaSocket([start_message(), media_message(b"\x03" * FRAME_BYTES)])
        session = await run_echo_session(socket)
        assert session.inbound_frames == 1
        assert not session.stopped
        assert socket.closed
