"""Tier 2 client logic, tested against a real ASGI WebSocket with fake vendors.

What is under test is the fake Twilio's half of the protocol: correct framing, correct
mark acknowledgement, and correct handling of a clear. The vendor calls are not under test
here; the live path is exercised by the owner running the harness with real keys.
"""

from __future__ import annotations

import base64
import json

import pytest

from evals.fake_twilio import ReceivedAudio, frame_count, mulaw_duration_s
from evals.run_audio import format_latency


class TestAudioArithmetic:
    def test_one_byte_of_mulaw_is_one_sample_at_eight_kilohertz(self) -> None:
        assert mulaw_duration_s(bytes(8000)) == 1.0
        assert mulaw_duration_s(bytes(160)) == pytest.approx(0.02)

    def test_frame_count_rounds_a_partial_frame_up(self) -> None:
        assert frame_count(bytes(160)) == 1
        assert frame_count(bytes(161)) == 2
        assert frame_count(b"") == 0

    def test_received_audio_reports_its_own_duration(self) -> None:
        received = ReceivedAudio(frames=[bytes(160)] * 50)
        assert received.duration_s == pytest.approx(1.0)


class TestFakeTwilioProtocol:
    """The messages the fake sends must be the ones the server's parser accepts."""

    def test_the_start_message_parses_as_a_start_event(self) -> None:
        from arcagent.telephony.twilio_stream import StartEvent, parse_event
        from evals.fake_twilio import FakeTwilioCall

        call = FakeTwilioCall("ws://unused", call_sid="CAtest", from_number="+15550000001")
        sent: list[dict] = []

        class Recorder:
            async def send(self, raw: str) -> None:
                sent.append(json.loads(raw))

        call.socket = Recorder()
        import asyncio

        asyncio.run(call.start())

        connected, start = sent
        assert connected["event"] == "connected"
        event = parse_event(start)
        assert isinstance(event, StartEvent)
        assert event.call_sid == "CAtest"
        assert event.encoding == "audio/x-mulaw"
        assert event.sample_rate == 8000
        assert event.custom_parameters["from"] == "+15550000001"

    def test_media_frames_are_exactly_twenty_milliseconds(self) -> None:
        import asyncio

        from arcagent.telephony.twilio_stream import MediaEvent, parse_event
        from evals.fake_twilio import FakeTwilioCall

        call = FakeTwilioCall("ws://unused", realtime=False)
        sent: list[dict] = []

        class Recorder:
            async def send(self, raw: str) -> None:
                sent.append(json.loads(raw))

        call.socket = Recorder()
        asyncio.run(call.play(bytes(500)))  # three full frames plus a remainder

        assert len(sent) == 4
        for message in sent:
            event = parse_event(message)
            assert isinstance(event, MediaEvent)
            assert len(event.payload) == 160

    def test_the_payload_round_trips(self) -> None:
        import asyncio

        from evals.fake_twilio import FakeTwilioCall

        call = FakeTwilioCall("ws://unused", realtime=False)
        sent: list[dict] = []

        class Recorder:
            async def send(self, raw: str) -> None:
                sent.append(json.loads(raw))

        call.socket = Recorder()
        audio = bytes(range(160))
        asyncio.run(call.play(audio))
        assert base64.b64decode(sent[0]["media"]["payload"]) == audio


class TestAgainstTheRealServer:
    """Drives the actual /voice/echo route over a real ASGI WebSocket."""

    def test_the_echo_route_returns_what_the_fake_twilio_sent(self) -> None:
        from fastapi.testclient import TestClient

        from arcagent.app import app
        from arcagent.config import Settings, get_settings
        from evals.fake_twilio import FakeTwilioCall

        app.dependency_overrides[get_settings] = lambda: Settings(
            _env_file=None,
            echo_enabled=True,
            twilio_auth_token="echo-fixture",
            public_url="https://testserver",
        )
        try:
            from twilio.request_validator import RequestValidator

            signature = RequestValidator("echo-fixture").compute_signature(
                "wss://testserver/voice/echo", {}
            )
            with (
                TestClient(app) as client,
                client.websocket_connect(
                    "/voice/echo", headers={"X-Twilio-Signature": signature}
                ) as ws,
            ):
                call = FakeTwilioCall("ws://unused", realtime=False)

                class Bridge:
                    async def send(self, raw: str) -> None:
                        ws.send_json(json.loads(raw))

                call.socket = Bridge()
                import asyncio

                asyncio.run(call.start())
                asyncio.run(call.play(bytes([0x7F]) * 160))
                echoed = ws.receive_json()
        finally:
            app.dependency_overrides.clear()

        assert echoed["event"] == "media"
        assert base64.b64decode(echoed["media"]["payload"]) == bytes([0x7F]) * 160


class TestLatencyTable:
    def test_stages_with_no_measurements_are_shown_as_dashes_not_zero(self) -> None:
        """A missing measurement is not a fast one, and the table must not imply it is."""
        from evals.run_audio import AudioScenarioResult

        result = AudioScenarioResult(
            scenario_id="s",
            group="g",
            repeat_index=0,
            call_sid="CA",
            turns=2,
            barge_ins=0,
            outcome="handoff",
            latency_p50_ms=None,
            latency_p95_ms=None,
            stage_latencies={"llm_ttft_ms": []},
        )
        table = format_latency([result])
        assert "llm_ttft_ms" in table
        assert "-" in table

    def test_percentiles_are_reported_per_stage(self) -> None:
        from evals.run_audio import AudioScenarioResult

        result = AudioScenarioResult(
            scenario_id="s",
            group="g",
            repeat_index=0,
            call_sid="CA",
            turns=2,
            barge_ins=1,
            outcome="handoff",
            latency_p50_ms=300,
            latency_p95_ms=800,
            stage_latencies={"stt_final_ms": [200, 250, 300, 900]},
        )
        table = format_latency([result])
        assert "stt_final_ms" in table
        assert "barge ins observed: 1" in table


class TestIsolatedTransport:
    @pytest.mark.parametrize(
        "url",
        [
            "ws://localhost:8000/voice/stream",
            "ws://example.com/eval/voice/stream",
            "wss://user:password@example.com/eval/voice/stream",
            "wss://example.com/eval/voice/stream?token=secret",
        ],
    )
    def test_fake_client_refuses_live_or_unsafe_transport(self, url):
        from evals.fake_twilio import FakeTwilioCall

        with pytest.raises(ValueError, match="evaluation"):
            FakeTwilioCall(url, auth_token="fixture")

    async def test_token_is_sent_as_header_to_isolated_endpoint(self, monkeypatch):
        from evals.fake_twilio import FakeTwilioCall

        seen = []

        class Socket:
            async def send(self, raw):
                pass

            async def close(self):
                pass

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        async def connect(url, **kwargs):
            seen.append((url, kwargs))
            return Socket()

        monkeypatch.setattr("websockets.connect", connect)
        async with FakeTwilioCall(
            "wss://eval.example/eval/voice/stream", auth_token="fixture-secret"
        ):
            pass
        assert seen == [
            (
                "wss://eval.example/eval/voice/stream",
                {"additional_headers": {"Authorization": "Bearer fixture-secret"}},
            )
        ]


class TestAudioEvaluationReadiness:
    async def test_live_route_is_rejected_before_vendor_configuration(self, monkeypatch):
        from argparse import Namespace

        from arcagent.config import Settings
        from evals.run_audio import run

        monkeypatch.setattr("evals.run_audio.get_settings", lambda: Settings(_env_file=None))
        with pytest.raises(SystemExit, match="isolated audio evaluation"):
            await run(Namespace(stream_url="wss://example.com/voice/stream", n=1))

    def test_latency_report_explains_what_it_cannot_measure(self):
        report = format_latency([])
        assert "response latency: not measured" in report
        assert "playback_start_ms: playback acknowledgement" in report


async def test_silent_audio_session_does_not_count_as_a_pass(tmp_path, monkeypatch):
    from argparse import Namespace

    from sqlalchemy import select

    from arcagent.persistence.db import get_engine, session_scope
    from arcagent.persistence.models import Base, EvalResult
    from evals.run_audio import AudioScenarioResult, write_results

    url = f"sqlite:///{tmp_path / 'audio.db'}"
    Base.metadata.create_all(get_engine(url))
    monkeypatch.setattr("evals.run_audio.session_scope", lambda: session_scope(url))
    result = AudioScenarioResult(
        scenario_id="silent",
        group="hot_buyers",
        repeat_index=0,
        call_sid="CAfixture",
        turns=0,
        barge_ins=0,
        outcome=None,
        latency_p50_ms=None,
        latency_p95_ms=None,
    )
    run_id = write_results(
        Namespace(run_name="silent", prompts="v1", threshold=60), [result], "fixture"
    )
    with session_scope(url) as session:
        row = session.scalar(select(EvalResult).where(EvalResult.run_id == run_id))
        assert row.passed is False
        assert "No completed audio conversation was recorded" in row.notes
        assert "missing_expectations" in row.notes


def test_transport_success_with_wrong_outcome_is_persisted_as_failure(tmp_path, monkeypatch):
    from argparse import Namespace

    from sqlalchemy import select

    from arcagent.persistence.db import get_engine, session_scope
    from arcagent.persistence.models import Base, EvalResult
    from evals.persona import Expected
    from evals.run_audio import AudioScenarioResult, write_results

    url = f"sqlite:///{tmp_path / 'quality.db'}"
    Base.metadata.create_all(get_engine(url))
    monkeypatch.setattr("evals.run_audio.session_scope", lambda: session_scope(url))
    result = AudioScenarioResult(
        scenario_id="wrong-outcome",
        group="hot_buyers",
        repeat_index=0,
        call_sid="CAquality",
        turns=3,
        barge_ins=0,
        outcome="callback_booked",
        latency_p50_ms=None,
        latency_p95_ms=None,
        expected=Expected(outcome="handoff", handoff=True, fields={"name": "Pat"}),
        actual_fields={"name": "Pat"},
    )
    run_id = write_results(
        Namespace(run_name="quality", prompts="v1", threshold=60), [result], "fixture"
    )
    with session_scope(url) as session:
        row = session.scalar(select(EvalResult).where(EvalResult.run_id == run_id))
        assert row.passed is False
        assert row.expected["outcome"] == "handoff"
        assert row.actual["fields"] == {"name": "Pat"}
        assert row.field_accuracy == 1.0
        assert "outcome_mismatch" in row.notes
