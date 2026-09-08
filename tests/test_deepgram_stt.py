"""Deepgram client: URL construction, message parsing, reconnection, and teardown."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlparse

import pytest

from arcagent.config import Settings
from arcagent.speech.deepgram_stt import (
    CLOSE_MESSAGE,
    KEEPALIVE_MESSAGE,
    DeepgramSTT,
    SpeechStartedEvent,
    SttSocketClosed,
    TranscriptEvent,
    UtteranceEndEvent,
    auth_headers,
    build_stream_url,
    parse_message,
)
from tests.fakes import (
    FakeSttSocket,
    dg_metadata,
    dg_results,
    dg_speech_started,
    dg_utterance_end,
)


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, deepgram_api_key="dg_test_key", **overrides)


class TestStreamUrl:
    def test_audio_parameters_match_the_twilio_wire_format(self) -> None:
        params = parse_qs(urlparse(build_stream_url(settings())).query)
        assert params["encoding"] == ["mulaw"]
        assert params["sample_rate"] == ["8000"]
        assert params["channels"] == ["1"]

    def test_endpointing_comes_from_settings(self) -> None:
        url = build_stream_url(settings(deepgram_endpointing_ms=300, deepgram_utterance_end_ms=900))
        params = parse_qs(urlparse(url).query)
        assert params["endpointing"] == ["300"]
        assert params["utterance_end_ms"] == ["900"]

    def test_interim_and_vad_events_are_on(self) -> None:
        params = parse_qs(urlparse(build_stream_url(settings())).query)
        assert params["interim_results"] == ["true"]
        assert params["vad_events"] == ["true"]
        assert params["smart_format"] == ["true"]

    def test_language_is_omitted_unless_requested(self) -> None:
        assert "language=" not in build_stream_url(settings())
        assert "language=es" in build_stream_url(settings(), language="es")

    def test_api_key_travels_in_the_header_not_the_url(self) -> None:
        assert "dg_test_key" not in build_stream_url(settings())
        assert auth_headers(settings()) == {"Authorization": "Token dg_test_key"}


class TestParsing:
    def test_interim_transcript(self) -> None:
        event = parse_message(dg_results("i need a", start=0.5, duration=0.8), ts=100.0)
        assert isinstance(event, TranscriptEvent)
        assert event.text == "i need a"
        assert not event.is_final
        assert not event.speech_final
        assert event.ts == 100.0
        assert event.start_s == 0.5
        assert event.duration_s == 0.8
        assert event.word_count == 3

    def test_final_transcript(self) -> None:
        event = parse_message(dg_results("full arch", is_final=True, speech_final=True), ts=1.0)
        assert isinstance(event, TranscriptEvent)
        assert event.is_final
        assert event.speech_final

    def test_transcript_is_stripped(self) -> None:
        event = parse_message(dg_results("  hello  "), ts=1.0)
        assert isinstance(event, TranscriptEvent)
        assert event.text == "hello"

    def test_detected_language_is_carried_through(self) -> None:
        event = parse_message(dg_results("hola", detected_language="es"), ts=1.0)
        assert isinstance(event, TranscriptEvent)
        assert event.language == "es"

    def test_utterance_end(self) -> None:
        event = parse_message(dg_utterance_end(2.25), ts=5.0)
        assert isinstance(event, UtteranceEndEvent)
        assert event.last_word_end == 2.25

    def test_speech_started(self) -> None:
        event = parse_message(dg_speech_started(0.75), ts=5.0)
        assert isinstance(event, SpeechStartedEvent)
        assert event.timestamp == 0.75

    def test_metadata_is_ignored(self) -> None:
        assert parse_message(dg_metadata(), ts=1.0) is None

    def test_unknown_type_is_ignored_not_fatal(self) -> None:
        assert parse_message(json.dumps({"type": "SomethingNew"}), ts=1.0) is None

    def test_results_with_no_alternatives_is_ignored(self) -> None:
        assert parse_message(json.dumps({"type": "Results", "channel": {}}), ts=1.0) is None

    def test_malformed_json_is_ignored_not_fatal(self) -> None:
        assert parse_message("{not json", ts=1.0) is None


class TestSession:
    async def test_audio_frames_go_out_as_binary(self) -> None:
        socket = FakeSttSocket()
        stt = DeepgramSTT(settings(), connect=_connector(socket))
        async with stt:
            await stt.send_audio(b"\xff" * 160)
            await stt.send_audio(b"\xfe" * 160)
        assert socket.audio_frames == [b"\xff" * 160, b"\xfe" * 160]

    async def test_events_arrive_in_order(self) -> None:
        socket = FakeSttSocket(
            [
                dg_speech_started(),
                dg_results("i need"),
                dg_results("i need implants", is_final=True, speech_final=True),
                dg_utterance_end(),
            ]
        )
        stt = DeepgramSTT(settings(), connect=_connector(socket))
        await stt.start()
        events = await _take(stt, 4)
        await stt.close()

        assert isinstance(events[0], SpeechStartedEvent)
        assert isinstance(events[1], TranscriptEvent) and not events[1].is_final
        assert isinstance(events[2], TranscriptEvent) and events[2].speech_final
        assert isinstance(events[3], UtteranceEndEvent)

    async def test_close_sends_closestream_and_ends_iteration(self) -> None:
        socket = FakeSttSocket([dg_results("hi", is_final=True)])
        stt = DeepgramSTT(settings(), connect=_connector(socket))
        await stt.start()
        await _take(stt, 1)
        await stt.close()

        assert CLOSE_MESSAGE in socket.control_messages
        assert socket.closed
        assert [e async for e in stt.events()] == []

    async def test_audio_sent_after_close_is_dropped_not_raised(self) -> None:
        socket = FakeSttSocket()
        stt = DeepgramSTT(settings(), connect=_connector(socket))
        await stt.start()
        await stt.close()
        await stt.send_audio(b"\xff" * 160)
        assert stt.dropped_frames == 1

    async def test_keepalive_is_sent_while_idle(self) -> None:
        socket = FakeSttSocket()
        stt = DeepgramSTT(settings(), connect=_connector(socket), sleep=_instant_sleep)
        await stt.start()
        for _ in range(20):
            await asyncio.sleep(0)
        await stt.close()
        assert KEEPALIVE_MESSAGE in socket.control_messages


class TestReconnect:
    async def test_a_dropped_socket_is_replaced_and_the_stream_continues(self) -> None:
        first = FakeSttSocket([dg_results("before", is_final=True), SttSocketClosed()])
        second = FakeSttSocket([dg_results("after", is_final=True)])
        sockets = [first, second]

        async def connect(url: str, headers: dict[str, str]):
            return sockets.pop(0)

        stt = DeepgramSTT(settings(), connect=connect, sleep=_instant_sleep)
        await stt.start()
        events = await _take(stt, 2)
        await stt.close()

        assert [e.text for e in events] == ["before", "after"]  # type: ignore[union-attr]
        assert stt.reconnects == 1

    async def test_reconnect_attempts_are_bounded(self) -> None:
        attempts = 0

        async def connect(url: str, headers: dict[str, str]):
            nonlocal attempts
            attempts += 1
            return FakeSttSocket([SttSocketClosed()])

        stt = DeepgramSTT(settings(), connect=connect, sleep=_instant_sleep, max_reconnects=3)
        await stt.start()
        assert [e async for e in stt.events()] == []
        assert attempts == 4  # the first connect plus three retries
        await stt.close()


def _connector(socket: FakeSttSocket):
    async def connect(url: str, headers: dict[str, str]) -> FakeSttSocket:
        return socket

    return connect


async def _instant_sleep(_delay: float) -> None:
    await asyncio.sleep(0)


async def _take(stt: DeepgramSTT, n: int) -> list:
    events = []
    async for event in stt.events():
        events.append(event)
        if len(events) == n:
            break
    return events


@pytest.fixture(autouse=True)
def _fail_fast_on_hangs():
    """Every test in this module must finish quickly; a hang means a task is not cancelled."""
    yield
