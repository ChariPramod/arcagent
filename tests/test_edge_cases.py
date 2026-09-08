"""Callers who should not be qualified, and the Spanish fallback."""

from __future__ import annotations

import json

import pytest

from arcagent.agent import edge_cases
from arcagent.agent.edge_cases import EdgeCase, LanguageWatch, detect
from arcagent.agent.graph import AgentConfig
from arcagent.agent.responder import GraphResponder
from tests.test_graph_transitions import MockLLM


class TestDetection:
    @pytest.mark.parametrize(
        ("utterance", "expected"),
        [
            ("sorry, wrong number", EdgeCase.WRONG_NUMBER),
            ("i didn't call a dentist", EdgeCase.WRONG_NUMBER),
            ("i was trying to reach the pharmacy", EdgeCase.WRONG_NUMBER),
            ("i need to reschedule my appointment", EdgeCase.EXISTING_PATIENT),
            ("i'm an existing patient", EdgeCase.EXISTING_PATIENT),
            ("i'm calling about my appointment", EdgeCase.EXISTING_PATIENT),
            ("i'm 16", EdgeCase.MINOR),
            ("i am only 15", EdgeCase.MINOR),
            ("i'm still in high school", EdgeCase.MINOR),
        ],
    )
    def test_edge_cases_are_recognised(self, utterance: str, expected: EdgeCase) -> None:
        assert detect(utterance) is expected

    @pytest.mark.parametrize(
        "utterance",
        [
            "i need an appointment for a consultation",
            "i'm missing four teeth",
            "i'd like to book a consultation",
            "i'm 62 years old",
            "my husband is a patient here",
            "",
        ],
    )
    def test_ordinary_callers_are_not_diverted(self, utterance: str) -> None:
        """A false positive ends a call that should have continued, so these matter most."""
        assert detect(utterance) is None

    def test_an_adult_stating_their_age_is_not_a_minor(self) -> None:
        for age in ("i'm 18", "i am 45", "i'm 62 years old"):
            assert detect(age) is not EdgeCase.MINOR


class TestResponder:
    def _responder(self, replies=None) -> GraphResponder:
        return GraphResponder(AgentConfig(llm=MockLLM(replies or [])))

    async def test_the_greeting_comes_before_the_first_answer(self) -> None:
        responder = self._responder(
            [{"next_utterance": "Understood.", "treatment_interest": "full_arch"}]
        )
        spoken = [line async for line in responder.respond("i need all my teeth done")]
        assert "recorded" in spoken[0].lower()
        assert spoken[1] == "Understood."

    async def test_a_wrong_number_ends_the_call_and_creates_no_lead(self) -> None:
        responder = self._responder()
        [line async for line in responder.greet()]
        spoken = [line async for line in responder.respond("sorry, wrong number")]
        assert "dental office" in spoken[0]
        assert responder.should_end
        assert responder.outcome == "wrong_number"
        assert not responder.creates_a_lead

    async def test_an_existing_patient_is_sent_to_the_front_desk(self) -> None:
        responder = self._responder()
        [line async for line in responder.greet()]
        spoken = [line async for line in responder.respond("i need to reschedule my appointment")]
        assert "call the office" in spoken[0]
        assert responder.outcome == "not_a_lead"
        assert not responder.creates_a_lead

    async def test_a_minor_is_asked_for_a_parent_and_qualification_stops(self) -> None:
        responder = self._responder()
        [line async for line in responder.greet()]
        spoken = [line async for line in responder.respond("i'm 16")]
        assert "parent or guardian" in spoken[0]
        assert responder.should_end
        assert responder.outcome == "not_a_lead"

    async def test_an_edge_case_costs_no_model_call(self) -> None:
        llm = MockLLM()
        responder = GraphResponder(AgentConfig(llm=llm))
        [line async for line in responder.greet()]
        [line async for line in responder.respond("wrong number")]
        assert llm.calls == []

    async def test_a_normal_caller_reaches_the_graph(self) -> None:
        llm = MockLLM([{"next_utterance": "Understood.", "treatment_interest": "full_arch"}])
        responder = GraphResponder(AgentConfig(llm=llm))
        [line async for line in responder.greet()]
        [line async for line in responder.respond("i need all my upper teeth replaced")]
        assert llm.calls[0][0] == "TreatmentInterestOutput"
        assert responder.creates_a_lead


class TestSpanishFallback:
    def test_one_spanish_utterance_is_not_enough(self) -> None:
        """English speakers say gracias. One detection does not end an English call."""
        watch = LanguageWatch()
        assert not watch.observe("es")

    def test_two_in_a_row_falls_back(self) -> None:
        watch = LanguageWatch()
        watch.observe("es")
        assert watch.observe("es")

    def test_an_english_utterance_resets_the_count(self) -> None:
        watch = LanguageWatch()
        watch.observe("es")
        watch.observe("en")
        assert not watch.observe("es")

    def test_an_empty_detection_is_ignored(self) -> None:
        watch = LanguageWatch()
        watch.observe("es")
        watch.observe("")
        assert watch.observe("es")

    async def test_the_responder_reports_a_language_fallback_outcome(self) -> None:
        responder = GraphResponder(AgentConfig(llm=MockLLM()))
        assert not responder.observe_language("es")
        assert responder.observe_language("es")
        assert responder.outcome == "language_fallback"

    def test_the_spanish_message_asks_for_a_number_by_keypad(self) -> None:
        """Deepgram is configured for English, so the number comes in as DTMF, not speech."""
        assert "numeral" in edge_cases.SPANISH_FALLBACK
        assert "espanol" in edge_cases.SPANISH_FALLBACK


def _payload(**fields) -> str:
    return json.dumps(fields)


class TestLanguageFallbackInTheCallSession:
    """The Spanish path, driven through the real session with fake sockets."""

    async def test_two_spanish_transcripts_trigger_the_fixed_message(self) -> None:
        from arcagent.agent.edge_cases import SPANISH_FALLBACK
        from tests.fakes import dg_results, media_message
        from tests.harness import FRAME, build_harness

        harness = build_harness(GraphResponder(AgentConfig(llm=MockLLM())))
        await harness.start()
        harness.twilio.push(media_message(FRAME))
        for _ in range(2):
            harness.stt_socket.push(
                dg_results(
                    "necesito implantes", is_final=True, speech_final=True, detected_language="es"
                )
            )
            await harness.settle()
        assert await harness.wait_until(lambda: harness.tts_socket.requests != [])
        transcripts = [r["transcript"] for r in harness.tts_socket.requests]
        await harness.stop()

        assert SPANISH_FALLBACK in transcripts
        assert harness.session.language_fallback
        assert harness.session.awaiting_dtmf

    async def test_the_keyed_number_is_collected_and_hash_ends_the_call(self) -> None:
        from tests.fakes import dg_results, dtmf_message, media_message
        from tests.harness import FRAME, build_harness

        harness = build_harness(GraphResponder(AgentConfig(llm=MockLLM())))
        await harness.start()
        harness.twilio.push(media_message(FRAME))
        for _ in range(2):
            harness.stt_socket.push(
                dg_results("hola", is_final=True, speech_final=True, detected_language="es")
            )
            await harness.settle()
        assert await harness.wait_until(lambda: harness.session.awaiting_dtmf)

        for digit in "4155550123":
            harness.twilio.push(dtmf_message(digit))
        harness.twilio.push(dtmf_message("#"))
        assert await harness.wait_until(lambda: harness.session.state.name == "ENDING")
        await harness.stop()

        assert "".join(harness.session.dtmf_digits) == "4155550123"

    async def test_an_english_caller_never_falls_back(self) -> None:
        from tests.fakes import dg_results, media_message
        from tests.harness import FRAME, build_harness

        llm = MockLLM([{"next_utterance": "Understood.", "treatment_interest": "full_arch"}])
        harness = build_harness(GraphResponder(AgentConfig(llm=llm)))
        await harness.start()
        harness.twilio.push(media_message(FRAME))
        harness.stt_socket.push(
            dg_results(
                "i need a full arch", is_final=True, speech_final=True, detected_language="en"
            )
        )
        assert await harness.wait_until(lambda: harness.tts_socket.requests != [])
        await harness.stop()
        assert not harness.session.language_fallback
