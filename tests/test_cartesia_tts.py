"""Cartesia client: request shape, chunk demultiplexing, cancellation, teardown."""

from __future__ import annotations

import pytest

from arcagent.config import Settings
from arcagent.speech.cartesia_tts import (
    OUTPUT_FORMAT,
    CartesiaTTS,
    TtsError,
    TtsSocketClosed,
    auth_headers,
    build_cancel,
    build_request,
    build_socket_url,
)
from tests.fakes import FakeTtsSocket


def settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        cartesia_api_key="ct_test_key",
        cartesia_voice_id="voice_test",
        **overrides,
    )


def _connector(socket: FakeTtsSocket):
    async def connect(url: str, headers: dict[str, str]) -> FakeTtsSocket:
        return socket

    return connect


class TestRequest:
    def test_output_format_is_the_twilio_wire_format(self) -> None:
        request = build_request(settings(), "hello", "ctx1")
        assert request["output_format"] == OUTPUT_FORMAT
        assert OUTPUT_FORMAT == {"container": "raw", "encoding": "pcm_mulaw", "sample_rate": 8000}

    def test_output_format_cannot_be_mutated_through_a_returned_request(self) -> None:
        build_request(settings(), "hello", "ctx1")["output_format"]["sample_rate"] = 44100
        assert OUTPUT_FORMAT["sample_rate"] == 8000

    def test_voice_and_model_come_from_settings(self) -> None:
        request = build_request(settings(cartesia_model_id="sonic-test"), "hi", "ctx1")
        assert request["model_id"] == "sonic-test"
        assert request["voice"] == {"mode": "id", "id": "voice_test"}

    def test_context_id_is_carried(self) -> None:
        assert build_request(settings(), "hi", "ctx-42")["context_id"] == "ctx-42"

    def test_cancel_message(self) -> None:
        assert build_cancel("ctx-42") == {"context_id": "ctx-42", "cancel": True}

    def test_api_key_travels_in_the_header_not_the_url(self) -> None:
        assert "ct_test_key" not in build_socket_url()
        assert auth_headers(settings())["X-API-Key"] == "ct_test_key"


class TestSynthesis:
    async def test_chunks_arrive_in_order_with_indices(self) -> None:
        socket = FakeTtsSocket([[b"\x01" * 160, b"\x02" * 160, b"\x03" * 80]])
        async with CartesiaTTS(settings(), connect=_connector(socket)) as tts:
            chunks = [c async for c in tts.synthesize("hello there")]

        assert [c.audio for c in chunks] == [b"\x01" * 160, b"\x02" * 160, b"\x03" * 80]
        assert [c.index for c in chunks] == [0, 1, 2]
        assert len({c.context_id for c in chunks}) == 1

    async def test_audio_is_raw_mulaw_not_base64(self) -> None:
        socket = FakeTtsSocket([[bytes([0xFF, 0x00, 0x7F])]])
        async with CartesiaTTS(settings(), connect=_connector(socket)) as tts:
            chunks = [c async for c in tts.synthesize("hi")]
        assert chunks[0].audio == bytes([0xFF, 0x00, 0x7F])

    async def test_first_chunk_timestamp_uses_the_injected_clock(self) -> None:
        ticks = iter([10.0, 10.1, 10.2, 10.3, 10.4])
        socket = FakeTtsSocket([[b"\x01" * 160]])
        async with CartesiaTTS(
            settings(), connect=_connector(socket), clock=lambda: next(ticks)
        ) as tts:
            chunks = [c async for c in tts.synthesize("hi")]
        assert chunks[0].ts == 10.0

    async def test_two_utterances_do_not_mix(self) -> None:
        socket = FakeTtsSocket([[b"\xaa" * 160], [b"\xbb" * 160]])
        async with CartesiaTTS(settings(), connect=_connector(socket)) as tts:
            first = [c async for c in tts.synthesize("one")]
            second = [c async for c in tts.synthesize("two")]
        assert first[0].audio == b"\xaa" * 160
        assert second[0].audio == b"\xbb" * 160
        assert first[0].context_id != second[0].context_id

    async def test_error_message_raises(self) -> None:
        socket = FakeTtsSocket()
        async with CartesiaTTS(settings(), connect=_connector(socket)) as tts:
            context_id = tts.new_context_id()
            stream = tts.synthesize("hi", context_id=context_id)
            socket.push({"type": "error", "context_id": context_id, "error": "voice not found"})
            with pytest.raises(TtsError, match="voice not found"):
                async for _ in stream:
                    pass

    async def test_undecodable_chunk_is_skipped_not_fatal(self) -> None:
        socket = FakeTtsSocket()
        async with CartesiaTTS(settings(), connect=_connector(socket)) as tts:
            context_id = tts.new_context_id()
            stream = tts.synthesize("hi", context_id=context_id)
            socket.push({"type": "chunk", "context_id": context_id, "data": "not base64!!"})
            socket.push({"type": "done", "context_id": context_id})
            assert [c async for c in stream] == []


class TestCancellation:
    async def test_cancel_stops_the_stream_and_tells_cartesia(self) -> None:
        socket = FakeTtsSocket()
        async with CartesiaTTS(settings(), connect=_connector(socket)) as tts:
            context_id = tts.new_context_id()
            stream = tts.synthesize("a long sentence", context_id=context_id)
            await anext(stream)  # request goes out, first chunk arrives
            await tts.cancel(context_id)
            assert [c async for c in stream] == []
        assert socket.cancels == [context_id]

    async def test_late_chunks_for_a_cancelled_context_are_dropped(self) -> None:
        socket = FakeTtsSocket()
        async with CartesiaTTS(settings(), connect=_connector(socket)) as tts:
            context_id = tts.new_context_id()
            stream = tts.synthesize("hi", context_id=context_id)
            await anext(stream)
            await tts.cancel(context_id)
            socket.push({"type": "chunk", "context_id": context_id, "data": "//8="})
            assert [c async for c in stream] == []

    async def test_cancelling_an_unknown_context_is_harmless(self) -> None:
        socket = FakeTtsSocket()
        async with CartesiaTTS(settings(), connect=_connector(socket)) as tts:
            await tts.cancel("never-existed")


class TestLifecycle:
    async def test_synthesize_before_start_raises(self) -> None:
        tts = CartesiaTTS(settings(), connect=_connector(FakeTtsSocket()))
        with pytest.raises(TtsSocketClosed):
            await anext(tts.synthesize("hi"))

    async def test_close_is_idempotent_and_closes_the_socket(self) -> None:
        socket = FakeTtsSocket()
        tts = CartesiaTTS(settings(), connect=_connector(socket))
        await tts.start()
        await tts.close()
        await tts.close()
        assert socket.closed
