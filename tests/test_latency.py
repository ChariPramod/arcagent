"""Latency accounting: the four budget stages and the end to end response time."""

from __future__ import annotations

from arcagent.telephony.latency import TurnTimings


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_a_complete_turn_populates_all_four_columns() -> None:
    clock = FakeClock()
    t = TurnTimings(clock=clock)

    t.mark_audio_frame()  # latest inbound frame at 0.0
    clock.advance(0.25)
    t.mark_stt_final()  # Deepgram final at 0.25
    t.mark_llm_start()
    clock.advance(0.30)
    t.mark_llm_first_token()  # first token at 0.55
    t.mark_tts_request()
    clock.advance(0.12)
    t.mark_tts_first_byte()  # first audio byte at 0.67
    t.mark_first_frame_written()
    clock.advance(0.08)
    t.mark_playback_started()  # Twilio mark at 0.75

    assert t.as_columns() == {
        "stt_final_ms": 250,
        "llm_ttft_ms": 300,
        "tts_first_byte_ms": 120,
        "playback_start_ms": 80,
    }
    assert t.response_ms == 420  # transcript receipt to first frame on the wire


def test_stages_that_did_not_run_are_none_not_zero() -> None:
    t = TurnTimings(clock=FakeClock())
    assert t.as_columns() == {
        "stt_final_ms": None,
        "llm_ttft_ms": None,
        "tts_first_byte_ms": None,
        "playback_start_ms": None,
    }


def test_parrot_turn_has_no_llm_time_but_keeps_the_other_stages() -> None:
    clock = FakeClock()
    t = TurnTimings(clock=clock)
    t.mark_audio_frame()
    clock.advance(0.2)
    t.mark_stt_final()
    t.mark_tts_request()
    clock.advance(0.1)
    t.mark_tts_first_byte()
    columns = t.as_columns()
    assert columns["llm_ttft_ms"] is None
    assert columns["stt_final_ms"] == 200
    assert columns["tts_first_byte_ms"] == 100


def test_only_the_first_mark_of_each_stage_counts() -> None:
    clock = FakeClock()
    t = TurnTimings(clock=clock)
    t.mark_tts_request()
    clock.advance(0.1)
    t.mark_tts_first_byte()
    clock.advance(5.0)
    t.mark_tts_first_byte()  # a later chunk must not overwrite first byte
    assert t.as_columns()["tts_first_byte_ms"] == 100


def test_stt_proxy_uses_latest_inbound_frame_including_silence() -> None:
    clock = FakeClock()
    t = TurnTimings(clock=clock)
    for _ in range(50):  # a second of frames
        t.mark_audio_frame()
        clock.advance(0.02)
    t.mark_stt_final()
    assert t.as_columns()["stt_final_ms"] == 20


def test_an_out_of_order_clock_never_produces_a_negative_duration() -> None:
    t = TurnTimings(clock=FakeClock())
    t.last_audio_frame_at = 10.0
    t.stt_final_at = 9.5
    assert t.as_columns()["stt_final_ms"] == 0


def test_stt_boundary_can_use_timestamp_captured_on_receipt() -> None:
    clock = FakeClock()
    t = TurnTimings(clock=clock)
    t.mark_audio_frame()
    t.mark_stt_final(at=clock.now + 0.31)
    assert t.as_columns()["stt_final_ms"] == 310
