"""The parrot round trip: Twilio in, Deepgram, agent, Cartesia, Twilio out."""

from __future__ import annotations

import base64

from arcagent.telephony.call_session import SessionState
from tests.fakes import mark_message, stop_message
from tests.harness import ScriptedResponder, build_harness

FRAME_BYTES = 160


class TestParrot:
    async def test_the_caller_hears_back_what_they_said(self) -> None:
        harness = build_harness(tts_responses=[[b"\x11" * 320]])
        await harness.start()
        await harness.caller_says("i need a full arch")
        assert await harness.wait_until(lambda: harness.twilio.media_count >= 2)
        await harness.stop()

        assert harness.tts_socket.requests[0]["transcript"] == "i need a full arch"
        assert harness.twilio.sent_media_payloads()[:2] == [b"\x11" * 160, b"\x11" * 160]

    async def test_caller_audio_reaches_deepgram_unchanged(self) -> None:
        harness = build_harness()
        await harness.start()
        await harness.caller_says("hello")
        await harness.stop()
        assert harness.stt_socket.audio_frames[0] == b"\xff" * FRAME_BYTES

    async def test_every_outbound_frame_is_exactly_twenty_milliseconds(self) -> None:
        # 500 bytes is three full frames and a 20 byte remainder.
        harness = build_harness(tts_responses=[[b"\x22" * 500]])
        await harness.start()
        await harness.caller_says("hello")
        assert await harness.wait_until(lambda: harness.twilio.sent_of("mark") != [])
        await harness.stop()

        payloads = harness.twilio.sent_media_payloads()
        assert payloads, "no audio was written"
        assert all(len(p) == FRAME_BYTES for p in payloads)

    async def test_a_mark_follows_the_last_frame_of_an_utterance(self) -> None:
        harness = build_harness(tts_responses=[[b"\x33" * 320]])
        await harness.start()
        await harness.caller_says("hello")
        assert await harness.wait_until(lambda: harness.twilio.sent_of("mark") != [])
        await harness.stop()

        events = [m["event"] for m in harness.twilio.sent]
        assert events[-1] == "mark"
        assert events.count("mark") == 1

    async def test_both_speakers_are_recorded_as_turns(self) -> None:
        harness = build_harness(ScriptedResponder(["how can i help"]))
        await harness.start()
        await harness.caller_says("hi there")
        assert await harness.wait_until(lambda: len(harness.turns) >= 2)
        await harness.stop()

        assert [t.speaker for t in harness.turns[:2]] == ["caller", "agent"]
        assert harness.turns[0].text == "hi there"
        assert harness.turns[1].text == "how can i help"
        assert harness.turns[1].node_name == "test_node"

    async def test_the_agent_turn_carries_all_four_latency_columns(self) -> None:
        harness = build_harness(ScriptedResponder(["understood"]))
        await harness.start()
        await harness.caller_says("hi")
        assert await harness.wait_until(lambda: len(harness.turns) >= 2)
        harness.twilio.push(mark_message(harness.session.stream.pending_marks[0]))
        await harness.settle()
        await harness.stop()

        agent_turn = next(t for t in harness.turns if t.speaker == "agent")
        assert set(agent_turn.latency) == {
            "stt_final_ms",
            "llm_ttft_ms",
            "tts_first_byte_ms",
            "playback_start_ms",
        }
        assert agent_turn.latency["stt_final_ms"] is not None
        assert agent_turn.latency["tts_first_byte_ms"] is not None


class TestTurnState:
    async def test_the_session_speaks_then_returns_to_listening_on_the_mark(self) -> None:
        harness = build_harness(tts_responses=[[b"\x44" * 320]])
        await harness.start()
        assert harness.session.state is SessionState.LISTENING

        await harness.caller_says("hello")
        assert await harness.wait_until(lambda: harness.twilio.sent_of("mark") != [])
        assert harness.session.state is SessionState.SPEAKING

        harness.twilio.push(mark_message(harness.session.stream.pending_marks[0]))
        assert await harness.wait_until(lambda: harness.session.state is SessionState.LISTENING)
        await harness.stop()

    async def test_interim_transcripts_do_not_start_a_turn(self) -> None:
        harness = build_harness(ScriptedResponder())
        await harness.start()
        await harness.caller_says("i was thinking", is_final=False, speech_final=False)
        await harness.settle()
        await harness.stop()
        assert harness.tts_socket.requests == []

    async def test_empty_transcripts_are_ignored(self) -> None:
        harness = build_harness(ScriptedResponder())
        await harness.start()
        await harness.caller_says("")
        await harness.settle()
        await harness.stop()
        assert harness.turns == []


class TestHangup:
    async def test_a_stop_event_ends_the_call(self) -> None:
        harness = build_harness()
        await harness.start()
        harness.twilio.push(stop_message())
        assert await harness.wait_until(lambda: harness.session.stream.stopped)
        await harness.stop()
        assert harness.session.state is SessionState.ENDING

    async def test_audio_is_not_written_before_the_start_event(self) -> None:
        """No streamSid means nothing can be addressed to Twilio yet."""
        harness = build_harness()
        assert harness.session.stream.stream_sid == ""
        assert not any(
            base64.b64decode(m["media"]["payload"])
            for m in harness.twilio.sent
            if m.get("event") == "media"
        )
