"""Barge in and silence, held to docs/turn_taking.md.

These tests interrupt the agent mid utterance and assert on the exact sequence: clear
sent, TTS cancelled, no further audio from the abandoned utterance, and the interrupted
turn recorded with what the agent actually got through.
"""

from __future__ import annotations

import asyncio

from arcagent.agent.edge_cases import SILENCE_GOODBYE, SILENCE_REPROMPT
from arcagent.config import Settings
from arcagent.telephony.call_session import SessionState
from tests.fakes import dg_results, mark_message, media_message
from tests.harness import FRAME, ScriptedResponder, build_harness


def settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        deepgram_api_key="dg_test",
        cartesia_api_key="ct_test",
        cartesia_voice_id="voice_test",
        **overrides,
    )


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def _start_long_utterance(harness, reply: str = "implants usually take two visits and"):
    """Get the agent mid utterance with more audio still to come."""
    await harness.start()
    await harness.caller_says("tell me about implants")
    assert await harness.wait_until(lambda: harness.tts_socket.requests != [])
    context_id = harness.tts_socket.requests[0]["context_id"]
    harness.tts_socket.push_chunk(context_id, b"\x01" * 160)
    harness.tts_socket.push_chunk(context_id, b"\x02" * 160)
    assert await harness.wait_until(lambda: harness.twilio.media_count >= 2)
    return context_id


class TestBargeIn:
    async def test_a_final_transcript_while_speaking_sends_clear(self) -> None:
        harness = build_harness(ScriptedResponder(["a long answer"]), tts_auto=False)
        await _start_long_utterance(harness)
        assert harness.session.state is SessionState.SPEAKING

        harness.stt_socket.push(dg_results("wait", is_final=True, speech_final=True))
        assert await harness.wait_until(lambda: harness.twilio.sent_of("clear") != [])
        await harness.stop()

        assert harness.session.state in (SessionState.LISTENING, SessionState.ENDING)
        assert harness.session.barge_ins == 1

    async def test_the_abandoned_utterance_produces_no_further_audio(self) -> None:
        harness = build_harness(ScriptedResponder(["a long answer"]), tts_auto=False)
        context_id = await _start_long_utterance(harness)
        frames_before = harness.twilio.media_count

        harness.stt_socket.push(dg_results("stop", is_final=True, speech_final=True))
        assert await harness.wait_until(lambda: harness.twilio.sent_of("clear") != [])

        # Cartesia had already generated more audio for the abandoned utterance.
        for _ in range(5):
            harness.tts_socket.push_chunk(context_id, b"\x09" * 160)
        await harness.settle(200)

        new_frames = harness.twilio.sent_media_payloads()[frames_before:]
        assert b"\x09" * 160 not in new_frames, "audio from the interrupted utterance was played"
        await harness.stop()

    async def test_clear_is_sent_after_the_queue_is_drained_not_before(self) -> None:
        """Order matters: clearing first would let queued frames slip in behind the clear."""
        harness = build_harness(ScriptedResponder(["a long answer"]), tts_auto=False)
        context_id = await _start_long_utterance(harness)

        # Queue audio that has not been written yet, then interrupt in the same tick.
        for _ in range(10):
            harness.tts_socket.push_chunk(context_id, b"\x08" * 160)
        harness.stt_socket.push(dg_results("actually no", is_final=True, speech_final=True))
        assert await harness.wait_until(lambda: harness.twilio.sent_of("clear") != [])
        await harness.settle(200)
        await harness.stop()

        events = [m["event"] for m in harness.twilio.sent]
        clear_at = events.index("clear")
        assert "media" not in events[clear_at + 1 :] or all(
            p != b"\x08" * 160 for p in harness.twilio.sent_media_payloads()
        )

    async def test_cartesia_is_told_to_cancel_the_context(self) -> None:
        harness = build_harness(ScriptedResponder(["a long answer"]), tts_auto=False)
        context_id = await _start_long_utterance(harness)

        harness.stt_socket.push(dg_results("hold on", is_final=True, speech_final=True))
        assert await harness.wait_until(lambda: harness.tts_socket.cancels != [])
        await harness.stop()
        assert context_id in harness.tts_socket.cancels

    async def test_pending_marks_are_cleared_so_the_session_does_not_wait_forever(self) -> None:
        harness = build_harness(ScriptedResponder(["a long answer"]), tts_auto=False)
        await _start_long_utterance(harness)

        harness.stt_socket.push(dg_results("never mind", is_final=True, speech_final=True))
        assert await harness.wait_until(lambda: harness.twilio.sent_of("clear") != [])
        await harness.settle(100)
        assert not harness.session.stream.is_playing
        await harness.stop()

    async def test_the_interrupted_turn_is_recorded_as_interrupted(self) -> None:
        harness = build_harness(ScriptedResponder(["a long answer"]), tts_auto=False)
        context_id = await _start_long_utterance(harness)
        harness.tts_socket.push_done(context_id)
        assert await harness.wait_until(lambda: harness.twilio.sent_of("mark") != [])
        harness.twilio.push(mark_message(harness.twilio.sent_of("mark")[0]["mark"]["name"]))
        assert await harness.wait_until(lambda: any(t.speaker == "agent" for t in harness.turns))

        # Speak a second utterance and interrupt that one.
        harness.stt_socket.push(dg_results("one more thing", is_final=True, speech_final=True))
        assert await harness.wait_until(lambda: len(harness.tts_socket.requests) >= 2)
        second = harness.tts_socket.requests[1]["context_id"]
        harness.tts_socket.push_chunk(second, b"\x05" * 160)
        assert await harness.wait_until(lambda: harness.twilio.media_count >= 3)

        harness.stt_socket.push(dg_results("stop talking", is_final=True, speech_final=True))
        assert await harness.wait_until(lambda: harness.session.barge_ins == 1)
        await harness.settle(100)
        await harness.stop()

        assert any(t.interrupted for t in harness.turns if t.speaker == "agent")

    async def test_the_new_transcript_starts_a_fresh_turn(self) -> None:
        responder = ScriptedResponder(["a long answer", "sure, what would you like to know"])
        harness = build_harness(responder, tts_auto=False)
        await _start_long_utterance(harness)

        harness.stt_socket.push(dg_results("can i ask something", is_final=True, speech_final=True))
        assert await harness.wait_until(lambda: len(harness.tts_socket.requests) >= 2)
        await harness.stop()

        assert responder.heard == ["tell me about implants", "can i ask something"]
        assert harness.tts_socket.requests[1]["transcript"] == ("sure, what would you like to know")


class TestBackchannel:
    async def test_a_short_interim_does_not_interrupt(self) -> None:
        """ "uh huh" while the agent talks is a caller listening, not a caller interrupting."""
        harness = build_harness(ScriptedResponder(["a long answer"]), tts_auto=False)
        await _start_long_utterance(harness)

        harness.stt_socket.push(dg_results("uh huh", is_final=False, speech_final=False))
        await harness.settle(200)
        await harness.stop()

        assert harness.session.barge_ins == 0
        assert harness.twilio.sent_of("clear") == []

    async def test_a_long_interim_does_interrupt(self) -> None:
        harness = build_harness(ScriptedResponder(["a long answer"]), tts_auto=False)
        await _start_long_utterance(harness)

        harness.stt_socket.push(
            dg_results("no wait i have a question", is_final=False, speech_final=False)
        )
        assert await harness.wait_until(lambda: harness.twilio.sent_of("clear") != [])
        await harness.stop()
        assert harness.session.barge_ins == 1

    async def test_the_backchannel_threshold_is_configurable(self) -> None:
        harness = build_harness(
            ScriptedResponder(["a long answer"]),
            tts_auto=False,
            settings=settings(barge_in_min_words=6),
        )
        await _start_long_utterance(harness)

        harness.stt_socket.push(dg_results("no wait i have a", is_final=False, speech_final=False))
        await harness.settle(200)
        await harness.stop()
        assert harness.session.barge_ins == 0

    async def test_an_interim_while_listening_never_barges_in(self) -> None:
        harness = build_harness(ScriptedResponder())
        await harness.start()
        harness.stt_socket.push(
            dg_results("i have been thinking about this", is_final=False, speech_final=False)
        )
        await harness.settle(100)
        await harness.stop()
        assert harness.session.barge_ins == 0
        assert harness.twilio.sent_of("clear") == []


class TestSilence:
    async def test_no_speech_for_the_reprompt_window_triggers_one_reprompt(self) -> None:
        clock = FakeClock()
        harness = build_harness(
            ScriptedResponder(["are you still there", "second"]),
            settings=settings(silence_reprompt_s=8, silence_hangup_s=15),
            clock=clock,
        )
        await harness.start()
        clock.advance(9)
        assert await harness.wait_until(lambda: harness.tts_socket.requests != [], rounds=2000)
        await harness.stop()

        assert harness.session.reprompted
        assert harness.tts_socket.requests[0]["transcript"] == SILENCE_REPROMPT

    async def test_the_reprompt_happens_only_once(self) -> None:
        clock = FakeClock()
        harness = build_harness(
            ScriptedResponder(["are you still there", "again?"]),
            settings=settings(silence_reprompt_s=8, silence_hangup_s=600),
            clock=clock,
        )
        await harness.start()
        clock.advance(9)
        assert await harness.wait_until(lambda: harness.tts_socket.requests != [], rounds=2000)
        clock.advance(9)
        await harness.settle(2000)
        await harness.stop()
        assert len(harness.tts_socket.requests) == 1

    async def test_continued_silence_ends_the_call(self) -> None:
        clock = FakeClock()
        harness = build_harness(
            ScriptedResponder(["are you still there"]),
            settings=settings(silence_reprompt_s=8, silence_hangup_s=15),
            clock=clock,
        )
        await harness.start()
        clock.advance(16)
        assert await harness.wait_until(lambda: harness.twilio.sent_of("mark") != [], rounds=2000)
        assert harness.session.state is SessionState.SPEAKING
        harness.twilio.push(mark_message(harness.twilio.sent_of("mark")[0]["mark"]["name"]))
        assert await harness.wait_until(
            lambda: harness.session.state is SessionState.ENDING, rounds=2000
        )
        await harness.stop()
        assert harness.session.outcome == "abandoned"

    async def test_caller_speech_resets_the_silence_timer(self) -> None:
        clock = FakeClock()
        harness = build_harness(
            ScriptedResponder(["ok", "still ok"]),
            settings=settings(silence_reprompt_s=8, silence_hangup_s=15),
            clock=clock,
        )
        await harness.start()
        clock.advance(7)
        await harness.caller_says("i am here")
        clock.advance(7)
        await harness.settle(1000)
        await harness.stop()
        assert not harness.session.reprompted


class TestWriterIsTheOnlyAudioWriter:
    async def test_frames_and_marks_stay_in_order_under_repeated_interruption(self) -> None:
        """Three interruptions in a row must never interleave audio from two utterances."""
        responder = ScriptedResponder(["first answer", "second answer", "third answer", "fourth"])
        harness = build_harness(responder, tts_auto=False)
        await harness.start()

        seen: list[bytes] = []
        for index, filler in enumerate([b"\xa1", b"\xa2", b"\xa3"]):
            harness.twilio.push(media_message(FRAME))
            harness.stt_socket.push(
                dg_results(f"question number {index}", is_final=True, speech_final=True)
            )
            assert await harness.wait_until(
                lambda i=index: len(harness.tts_socket.requests) >= i + 1
            )
            context_id = harness.tts_socket.requests[index]["context_id"]
            for _ in range(3):
                harness.tts_socket.push_chunk(context_id, filler * 160)
            assert await harness.wait_until(
                lambda f=filler: f * 160 in harness.twilio.sent_media_payloads()
            )
            seen.append(filler * 160)

        await asyncio.sleep(0)
        payloads = harness.twilio.sent_media_payloads()
        await harness.stop()

        # Each utterance's audio must appear in one contiguous run, never interleaved.
        runs = [p for i, p in enumerate(payloads) if i == 0 or payloads[i - 1] != p]
        assert len(runs) == len(set(runs)), f"audio from two utterances interleaved: {runs}"


class TestShutdown:
    """A hangup must end the call even while the agent is mid utterance.

    Regression: cancelling a task that is awaiting another task delivers the cancellation
    to the awaited task, so a hangup looked exactly like a barge in and the agent loop
    started the next turn instead of exiting.
    """

    async def test_hangup_while_waiting_on_cartesia_ends_the_call(self) -> None:
        harness = build_harness(ScriptedResponder(["a long answer"]), tts_auto=False)
        await harness.start()
        await harness.caller_says("tell me about implants")
        assert await harness.wait_until(lambda: harness.tts_socket.requests != [])
        await harness.stop()  # asserts shutdown within two seconds
        assert harness.session.state is SessionState.ENDING

    async def test_hangup_with_a_turn_queued_behind_the_current_one_ends_the_call(self) -> None:
        harness = build_harness(ScriptedResponder(["one", "two", "three"]), tts_auto=False)
        await harness.start()
        await harness.caller_says("first question")
        assert await harness.wait_until(lambda: harness.tts_socket.requests != [])
        harness.stt_socket.push(dg_results("second question", is_final=True, speech_final=True))
        await harness.settle()
        await harness.stop()
        assert harness.session.state is SessionState.ENDING

    async def test_hangup_while_idle_ends_the_call(self) -> None:
        harness = build_harness(ScriptedResponder())
        await harness.start()
        await harness.stop()
        assert harness.session.state is SessionState.ENDING


class TestSilenceLines:
    """The lines the session speaks when the caller, not the agent, has gone quiet."""

    async def test_the_goodbye_is_spoken_before_the_call_ends(self) -> None:
        clock = FakeClock()
        harness = build_harness(
            ScriptedResponder(),
            settings=settings(silence_reprompt_s=600, silence_hangup_s=15),
            clock=clock,
        )
        await harness.start()
        clock.advance(16)
        assert await harness.wait_until(lambda: harness.tts_socket.requests != [], rounds=2000)
        await harness.stop()
        assert harness.tts_socket.requests[0]["transcript"] == SILENCE_GOODBYE

    async def test_a_caller_saying_the_sentinel_text_does_not_trigger_it(self) -> None:
        """The sentinels are compared by identity, so they are not sayable."""
        from arcagent.telephony.call_session import FIXED_LINES

        harness = build_harness(ScriptedResponder(["ok"]), tts_auto=True)
        await harness.start()
        await harness.caller_says(next(iter(FIXED_LINES)))
        assert await harness.wait_until(lambda: harness.tts_socket.requests != [])
        await harness.stop()
        assert harness.tts_socket.requests[0]["transcript"] == "ok"


async def test_failed_vendor_cancel_does_not_lose_the_interrupting_caller_turn() -> None:
    import json

    responder = ScriptedResponder(["first answer", "second answer"])
    harness = build_harness(responder, tts_auto=False)
    original_send = harness.tts_socket.send

    async def send_with_failed_cancel(data):
        if json.loads(data).get("cancel"):
            raise ConnectionError("vendor cancel unavailable")
        await original_send(data)

    harness.tts_socket.send = send_with_failed_cancel
    await _start_long_utterance(harness)
    try:
        await harness.caller_says("actually another question")
        assert await harness.wait_until(lambda: len(harness.tts_socket.requests) == 2)
        assert responder.heard == ["tell me about implants", "actually another question"]
    finally:
        await harness.stop()
