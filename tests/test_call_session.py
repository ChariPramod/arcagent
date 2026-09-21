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
        assert await harness.wait_until(lambda: harness.twilio.sent_of("mark") != [])
        harness.twilio.push(mark_message(harness.twilio.sent_of("mark")[0]["mark"]["name"]))
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
        assert await harness.wait_until(lambda: harness.twilio.sent_of("mark") != [])
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


class TestUtteranceAssembly:
    async def test_endpoint_preserves_every_final_segment(self) -> None:
        responder = ScriptedResponder()
        harness = build_harness(responder)
        await harness.start()
        try:
            await harness.caller_says("I need implants", speech_final=False)
            await harness.caller_says("and have insurance")
            assert await harness.wait_until(lambda: responder.heard != [])
            assert responder.heard == ["I need implants and have insurance"]
            assert [t.text for t in harness.turns if t.speaker == "caller"] == [
                "I need implants and have insurance"
            ]
        finally:
            await harness.stop()

    async def test_utterance_end_flushes_final_segments_without_an_endpoint(self) -> None:
        from tests.fakes import dg_utterance_end

        responder = ScriptedResponder()
        harness = build_harness(responder)
        await harness.start()
        try:
            await harness.caller_says("I need implants", speech_final=False)
            harness.stt_socket.push(dg_utterance_end())
            assert await harness.wait_until(lambda: responder.heard != [])
            harness.stt_socket.push(dg_utterance_end())
            await harness.caller_says("", speech_final=True)
            assert responder.heard == ["I need implants"]
        finally:
            await harness.stop()

    async def test_an_empty_endpoint_flushes_preceding_final_text(self) -> None:
        responder = ScriptedResponder()
        harness = build_harness(responder)
        await harness.start()
        try:
            await harness.caller_says("I need implants", speech_final=False)
            await harness.caller_says("")
            assert responder.heard == ["I need implants"]
        finally:
            await harness.stop()

    async def test_late_utterance_end_does_not_flush_the_next_utterance(self) -> None:
        from tests.fakes import dg_results, dg_utterance_end

        responder = ScriptedResponder()
        harness = build_harness(responder)
        await harness.start()
        try:
            harness.stt_socket.push(dg_results("first", True, True, start=0, duration=1))
            await harness.settle()
            harness.stt_socket.push(dg_results("second", True, False, start=3, duration=1))
            harness.stt_socket.push(dg_utterance_end(last_word_end=1))
            await harness.settle()
            assert responder.heard == ["first"]
            harness.stt_socket.push(dg_results("thought", True, True, start=4, duration=1))
            await harness.settle()
            assert responder.heard == ["first", "second thought"]
        finally:
            await harness.stop()


class TestPlaybackAccounting:
    async def test_agent_turn_is_persisted_with_its_own_playback_acknowledgement(self) -> None:
        from tests.test_latency import FakeClock

        clock = FakeClock()
        harness = build_harness(ScriptedResponder(["understood"]), clock=clock)
        await harness.start()
        try:
            await harness.caller_says("hi")
            assert await harness.wait_until(lambda: harness.twilio.sent_of("mark") != [])
            assert not [t for t in harness.turns if t.speaker == "agent"]
            clock.advance(0.75)
            harness.twilio.push(mark_message(harness.twilio.sent_of("mark")[0]["mark"]["name"]))
            assert await harness.wait_until(lambda: len(harness.turns) == 2)
            assert harness.turns[1].latency["playback_start_ms"] == 750
        finally:
            await harness.stop()

    async def test_terminal_reply_waits_for_playback_before_ending(self) -> None:
        responder = ScriptedResponder(["goodbye"])
        harness = build_harness(responder)
        await harness.start()
        try:
            responder.should_end = True
            await harness.caller_says("bye")
            assert await harness.wait_until(lambda: harness.twilio.sent_of("mark") != [])
            assert harness.session.state is SessionState.SPEAKING
            harness.twilio.push(mark_message(harness.twilio.sent_of("mark")[0]["mark"]["name"]))
            assert await harness.wait_until(lambda: harness.session.state is SessionState.ENDING)
            assert harness.turns[-1].text == "goodbye"
            assert not harness.turns[-1].interrupted
        finally:
            await harness.stop()

    async def test_late_mark_from_interrupted_turn_cannot_complete_the_next_turn(self) -> None:
        from tests.test_latency import FakeClock

        clock = FakeClock()
        harness = build_harness(ScriptedResponder(["first reply", "second reply"]), clock=clock)
        await harness.start()
        try:
            await harness.caller_says("first question")
            first_mark = harness.twilio.sent_of("mark")[0]["mark"]["name"]
            clock.advance(0.5)
            await harness.caller_says("second question")
            second_mark = harness.twilio.sent_of("mark")[1]["mark"]["name"]
            clock.advance(0.25)
            harness.twilio.push(mark_message(first_mark))
            await harness.settle()
            assert harness.session.state is SessionState.SPEAKING
            assert [t.text for t in harness.turns if t.speaker == "agent"] == ["first reply"]
            assert harness.turns[1].interrupted
            assert harness.turns[1].latency["playback_start_ms"] is None
            clock.advance(0.5)
            harness.twilio.push(mark_message(second_mark))
            await harness.settle()
            assert harness.turns[-1].text == "second reply"
            assert harness.turns[-1].latency["playback_start_ms"] == 750
            assert not harness.turns[-1].interrupted
        finally:
            await harness.stop()

    async def test_missing_playback_acknowledgement_has_a_bounded_wait(self) -> None:
        import asyncio

        harness = build_harness(ScriptedResponder(["goodbye"]))
        harness.session.playback_timeout_s = 0.01
        await harness.start()
        try:
            await harness.caller_says("bye")
            await asyncio.sleep(0.03)
            assert harness.session.state is SessionState.ENDING
            assert harness.turns[-1].interrupted
            assert harness.turns[-1].latency["playback_start_ms"] is None
            assert harness.twilio.sent_of("clear")
        finally:
            await harness.stop()

    async def test_marks_returned_by_clear_do_not_claim_successful_playback(self) -> None:
        harness = build_harness(ScriptedResponder(["first reply", "second reply"]))
        original_send = harness.twilio.send_json

        async def send_with_clear_ack(message):
            await original_send(message)
            if message["event"] == "clear":
                name = harness.twilio.sent_of("mark")[0]["mark"]["name"]
                harness.twilio.push(mark_message(name))
                await harness.settle()

        harness.twilio.send_json = send_with_clear_ack
        await harness.start()
        try:
            await harness.caller_says("first question")
            await harness.caller_says("second question")
            assert await harness.wait_until(
                lambda: any(t.speaker == "agent" for t in harness.turns)
            )
            first = next(t for t in harness.turns if t.speaker == "agent")
            assert first.interrupted
            assert first.latency["playback_start_ms"] is None
        finally:
            await harness.stop()

    async def test_synthesis_failure_ends_safely_instead_of_leaving_a_silent_call(self) -> None:
        harness = build_harness(ScriptedResponder(["reply"]), tts_auto=False)
        await harness.start()
        try:
            await harness.caller_says("question")
            context = harness.tts_socket.requests[0]["context_id"]
            harness.tts_socket.push({"type": "error", "context_id": context, "error": "failed"})
            assert await harness.wait_until(lambda: harness.session.state is SessionState.ENDING)
            assert harness.session.outcome == "abandoned"
            assert harness.turns[-1].interrupted
            assert harness.turns[-1].latency["playback_start_ms"] is None
        finally:
            await harness.stop()

    async def test_acknowledging_one_chunk_does_not_hide_the_next_active_synthesis(self) -> None:
        class ChunkedResponder(ScriptedResponder):
            async def respond(self, transcript):
                if transcript:
                    yield "first chunk"
                    yield "second chunk"

        harness = build_harness(ChunkedResponder(), tts_auto=False)
        await harness.start()
        try:
            await harness.caller_says("question")
            first_context = harness.tts_socket.requests[0]["context_id"]
            harness.tts_socket.push_chunk(first_context, b"\x01" * 160)
            harness.tts_socket.push_done(first_context)
            assert await harness.wait_until(lambda: len(harness.tts_socket.requests) == 2)
            assert await harness.wait_until(lambda: bool(harness.twilio.sent_of("mark")))
            harness.twilio.push(mark_message(harness.twilio.sent_of("mark")[0]["mark"]["name"]))
            await harness.settle()
            assert harness.session.state is SessionState.SPEAKING
            await harness.caller_says("wait", is_final=False, speech_final=False)
            assert harness.session.barge_ins == 0
            await harness.caller_says("actually wait a moment", is_final=False, speech_final=False)
            assert harness.session.barge_ins == 1
        finally:
            await harness.stop()

    async def test_hangup_before_terminal_playback_is_abandoned(self) -> None:
        responder = ScriptedResponder(["goodbye"])
        harness = build_harness(responder)
        await harness.start()
        responder.should_end = True
        await harness.caller_says("bye")
        assert await harness.wait_until(lambda: bool(harness.twilio.sent_of("mark")))
        await harness.stop()
        assert harness.session.outcome == "abandoned"
        assert harness.turns[-1].interrupted


class TestReplyCompletion:
    async def test_complete_reply_waits_for_all_chunks_and_persisted_turns(self) -> None:
        class ChunkedResponder(ScriptedResponder):
            async def respond(self, transcript):
                if transcript:
                    yield "first chunk"
                    yield "second chunk"

        harness = build_harness(ChunkedResponder())
        completions = []

        async def completed(texts, terminal):
            completions.append((texts, terminal, [t.text for t in harness.turns]))

        harness.session.on_reply_complete = completed
        await harness.start()
        try:
            await harness.caller_says("question")
            marks = harness.twilio.sent_of("mark")
            assert len(marks) == 2
            assert completions == []
            harness.twilio.push(mark_message(marks[0]["mark"]["name"]))
            await harness.settle()
            assert completions == []
            harness.twilio.push(mark_message(marks[1]["mark"]["name"]))
            await harness.settle()
            assert completions == [
                (
                    ["first chunk", "second chunk"],
                    False,
                    ["question", "first chunk", "second chunk"],
                )
            ]
        finally:
            await harness.stop()

    async def test_interrupted_reply_never_reports_completion(self) -> None:
        harness = build_harness(ScriptedResponder(["first reply", "second reply"]))
        completions = []

        async def completed(texts, terminal):
            completions.append((texts, terminal))

        harness.session.on_reply_complete = completed
        await harness.start()
        try:
            await harness.caller_says("first question")
            first_mark = harness.twilio.sent_of("mark")[0]["mark"]["name"]
            await harness.caller_says("second question")
            second_mark = harness.twilio.sent_of("mark")[1]["mark"]["name"]
            harness.twilio.push(mark_message(first_mark))
            await harness.settle()
            assert completions == []
            harness.twilio.push(mark_message(second_mark))
            await harness.settle()
            assert completions == [(["second reply"], False)]
        finally:
            await harness.stop()

    async def test_terminal_reply_reports_completion_before_ending(self) -> None:
        responder = ScriptedResponder(["goodbye"])
        harness = build_harness(responder)
        completions = []

        async def completed(texts, terminal):
            completions.append((texts, terminal, harness.session.state))

        harness.session.on_reply_complete = completed
        await harness.start()
        try:
            responder.should_end = True
            await harness.caller_says("bye")
            harness.twilio.push(mark_message(harness.twilio.sent_of("mark")[0]["mark"]["name"]))
            assert await harness.wait_until(lambda: harness.session.state is SessionState.ENDING)
            assert completions == [(["goodbye"], True, SessionState.LISTENING)]
        finally:
            await harness.stop()

    async def test_silence_goodbye_reports_terminal_completion_after_playback(self) -> None:
        from arcagent.agent.edge_cases import SILENCE_GOODBYE
        from tests.test_barge_in import FakeClock, settings

        clock = FakeClock()
        harness = build_harness(
            ScriptedResponder(), settings=settings(silence_hangup_s=15), clock=clock
        )
        completions = []

        async def completed(texts, terminal):
            completions.append((texts, terminal))

        harness.session.on_reply_complete = completed
        await harness.start()
        try:
            clock.advance(16)
            assert await harness.wait_until(lambda: bool(harness.twilio.sent_of("mark")))
            assert completions == []
            harness.twilio.push(mark_message(harness.twilio.sent_of("mark")[0]["mark"]["name"]))
            assert await harness.wait_until(lambda: harness.session.state is SessionState.ENDING)
            assert completions == [([SILENCE_GOODBYE], True)]
        finally:
            await harness.stop()

    async def test_disconnect_after_terminal_completion_does_not_abandon_completed_call(
        self,
    ) -> None:
        import asyncio

        responder = ScriptedResponder(["goodbye"])
        harness = build_harness(responder)
        callback_started = asyncio.Event()

        async def completed(texts, terminal):
            assert texts == ["goodbye"] and terminal
            callback_started.set()
            # A real socket send may yield while the remote sees completion and closes.
            harness.twilio.push(stop_message())
            await asyncio.Event().wait()

        harness.session.on_reply_complete = completed
        await harness.start()
        try:
            responder.should_end = True
            await harness.caller_says("bye")
            harness.twilio.push(mark_message(harness.twilio.sent_of("mark")[0]["mark"]["name"]))
            assert await harness.wait_until(callback_started.is_set)
            assert await harness.wait_until(lambda: harness.session.state is SessionState.ENDING)
            assert harness.session.outcome is None
            assert harness.turns[-1].text == "goodbye"
            assert not harness.turns[-1].interrupted
        finally:
            await harness.stop()
