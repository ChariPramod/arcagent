"""Graph transitions, driven by a mocked LLM returning fixed JSON.

No network, no key, no audio. What is under test is the flow: which node runs next, what
survives in state, and where an objection sends the conversation.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from arcagent.agent.graph import (
    CONTACT,
    END_CALL,
    INSURANCE,
    SITUATION,
    TREATMENT,
    AgentConfig,
    Conversation,
)
from arcagent.agent.llm import LLMError, LLMResult
from arcagent.agent.scoring import Decision
from arcagent.agent.state import ConsideringDuration, ObjectionKind, TreatmentInterest


class MockLLM:
    """Returns the next queued JSON payload, validated against the node's own schema.

    Validating against the real schema is the point: a payload the real model could not
    legally return fails the test rather than passing it.
    """

    def __init__(self, replies: list[dict[str, Any]] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[tuple[str, str]] = []
        self.systems: list[str] = []

    def queue(self, *payloads: dict[str, Any]) -> MockLLM:
        self.replies.extend(payloads)
        return self

    async def complete(self, system, messages, schema, model=None) -> LLMResult:
        self.calls.append((schema.__name__, model or "default"))
        self.systems.append(system)
        payload = self.replies.pop(0) if self.replies else {"next_utterance": "go on"}
        return LLMResult(
            parsed=schema.model_validate(payload),
            ttft_s=0.18,
            total_s=0.42,
            raw=json.dumps(payload),
        )


def conversation(llm: MockLLM, **config: Any) -> Conversation:
    return Conversation(AgentConfig(llm=llm, **config))


HOT_LEAD = [
    {"next_utterance": "A full arch, understood.", "treatment_interest": "full_arch"},
    {"next_utterance": "How long has it been hurting?", "pain_level": 8},
    {
        "next_utterance": "Do you have dental insurance?",
        "has_insurance": True,
        "employer_name": "Acme Logistics",
    },
    {
        "next_utterance": "What is the best number for you?",
        "name": "Bob Reyes",
        "callback_number": "4155550123",
    },
]


class TestHappyPath:
    async def test_the_greeting_carries_the_disclosure_and_needs_no_model(self) -> None:
        llm = MockLLM()
        convo = conversation(llm)
        spoken = await convo.start()
        assert len(spoken) == 1
        assert "recorded" in spoken[0].lower()
        assert "automated assistant" in spoken[0].lower()
        assert llm.calls == []

    async def test_nodes_run_in_the_designed_order(self) -> None:
        llm = MockLLM(HOT_LEAD)
        convo = conversation(llm)
        await convo.start()
        assert convo.state["current_node"] == TREATMENT
        await convo.say("i need all my teeth done")
        assert convo.state["current_node"] == SITUATION
        await convo.say("it hurts a lot")
        assert convo.state["current_node"] == INSURANCE
        await convo.say("yes through work")
        assert convo.state["current_node"] == CONTACT

    async def test_scoring_and_routing_happen_without_another_caller_turn(self) -> None:
        """After contact capture the agent scores and routes in the same breath."""
        llm = MockLLM(HOT_LEAD)
        convo = conversation(llm)
        await convo.start()
        for text in ["full arch", "hurts", "yes", "bob"]:
            spoken = await convo.say(text)
        assert convo.finished
        assert convo.decision is Decision.HANDOFF
        assert convo.outcome == "handoff"
        assert any("coordinator" in line for line in spoken)

    async def test_each_node_gets_its_own_schema(self) -> None:
        llm = MockLLM(HOT_LEAD)
        convo = conversation(llm)
        await convo.start()
        for text in ["full arch", "hurts", "yes", "bob"]:
            await convo.say(text)
        assert [name for name, _ in llm.calls] == [
            "TreatmentInterestOutput",
            "SituationOutput",
            "InsuranceOutput",
            "ContactOutput",
        ]

    async def test_the_shared_system_prompt_is_prepended_to_every_node(self) -> None:
        llm = MockLLM(HOT_LEAD)
        convo = conversation(llm)
        await convo.start()
        await convo.say("full arch")
        assert "automated assistant" in llm.systems[0]
        assert "confirm_treatment_interest" in llm.systems[0]


class TestExtractionAccumulates:
    async def test_fields_from_earlier_nodes_survive(self) -> None:
        llm = MockLLM(HOT_LEAD)
        convo = conversation(llm)
        await convo.start()
        for text in ["full arch", "hurts", "yes", "bob"]:
            await convo.say(text)
        fields = convo.fields
        assert fields.treatment_interest is TreatmentInterest.FULL_ARCH
        assert fields.pain_level == 8
        assert fields.has_insurance is True
        assert fields.employer_name == "Acme Logistics"
        assert fields.name == "Bob Reyes"

    async def test_a_null_does_not_erase_an_earlier_answer(self) -> None:
        """The model returning null means "not stated", never "the answer is nothing"."""
        llm = MockLLM(
            [
                {"next_utterance": "Got it.", "treatment_interest": "full_arch"},
                {"next_utterance": "And how long?", "pain_level": None},
                {"next_utterance": "Insurance?", "has_insurance": None},
            ]
        )
        convo = conversation(llm)
        await convo.start()
        await convo.say("full arch")
        await convo.say("not sure")
        await convo.say("dunno")
        assert convo.fields.treatment_interest is TreatmentInterest.FULL_ARCH

    async def test_a_node_cannot_write_a_field_it_does_not_own(self) -> None:
        """The schema has no such field, so an attempt is a validation error, not a write."""
        llm = MockLLM(
            [{"next_utterance": "Hi", "treatment_interest": "full_arch", "pain_level": 9}]
        )
        convo = conversation(llm)
        await convo.start()
        with pytest.raises(ValidationError):
            await convo.say("full arch")

    async def test_an_empty_string_is_treated_as_not_stated(self) -> None:
        llm = MockLLM(
            [
                {"next_utterance": "Got it.", "treatment_interest": "single_implant"},
                {"next_utterance": "ok", "considering_duration": "over_6_months"},
                {"next_utterance": "ok", "employer_name": "   ", "has_insurance": True},
            ]
        )
        convo = conversation(llm)
        await convo.start()
        await convo.say("one implant")
        await convo.say("about a year")
        await convo.say("yes")
        assert convo.fields.employer_name is None
        assert convo.fields.considering_duration is ConsideringDuration.OVER_6_MONTHS


class TestObjections:
    async def test_a_price_question_diverts_into_the_handler(self) -> None:
        llm = MockLLM(
            [
                {"next_utterance": "Understood.", "treatment_interest": "full_arch"},
                {
                    "next_utterance": "It depends on the case, let me ask a couple of things.",
                    "recovered": False,
                },
            ]
        )
        convo = conversation(llm)
        await convo.start()
        await convo.say("full arch")
        await convo.say("how much does this cost")
        assert llm.calls[-1][0] == "ObjectionOutput"
        assert convo.fields.objection(ObjectionKind.PRICE) is not None

    async def test_handling_returns_to_the_node_it_interrupted(self) -> None:
        llm = MockLLM(
            [
                {"next_utterance": "Understood.", "treatment_interest": "full_arch"},
                {"next_utterance": "Let me get a couple of details first.", "recovered": True},
            ]
        )
        convo = conversation(llm)
        await convo.start()
        await convo.say("full arch")
        assert convo.state["current_node"] == SITUATION
        await convo.say("how much is this going to cost me")
        assert convo.state["current_node"] == SITUATION
        assert convo.state["return_to"] is None

    async def test_an_unrecovered_objection_stays_open_and_penalises_the_score(self) -> None:
        llm = MockLLM(
            [
                {"next_utterance": "Understood.", "treatment_interest": "full_arch"},
                {"next_utterance": "I cannot quote a price on the phone.", "recovered": False},
            ]
        )
        convo = conversation(llm)
        await convo.start()
        await convo.say("full arch")
        await convo.say("how much does it cost")
        objection = convo.fields.objection(ObjectionKind.PRICE)
        assert objection is not None and not objection.recovered
        assert convo.state["open_objection"] == "price"

    async def test_the_same_objection_twice_does_not_loop(self) -> None:
        llm = MockLLM(
            [
                {"next_utterance": "Understood.", "treatment_interest": "full_arch"},
                {"next_utterance": "I cannot quote a price.", "recovered": False},
                {"next_utterance": "How long has it been hurting?", "pain_level": 4},
            ]
        )
        convo = conversation(llm)
        await convo.start()
        await convo.say("full arch")
        await convo.say("how much does it cost")
        await convo.say("but seriously how much")
        assert llm.calls[-1][0] == "SituationOutput"

    async def test_a_recovered_objection_can_be_raised_again_later(self) -> None:
        llm = MockLLM(
            [
                {"next_utterance": "Understood.", "treatment_interest": "full_arch"},
                {"next_utterance": "Let me get some details.", "recovered": True},
                {"next_utterance": "I hear you.", "recovered": False},
            ]
        )
        convo = conversation(llm)
        await convo.start()
        await convo.say("full arch")
        await convo.say("how much does it cost")
        await convo.say("i really cannot afford that")
        assert [o.recovered for o in convo.fields.objections] == [True, False]

    @pytest.mark.parametrize(
        ("utterance", "kind"),
        [
            ("how much does a full arch cost", ObjectionKind.PRICE),
            ("i am really scared of the surgery", ObjectionKind.FEAR),
            ("i am just looking for information", ObjectionKind.JUST_LOOKING),
            ("i need to talk to my wife first", ObjectionKind.SPOUSE),
            ("i had a bad experience at my last dentist", ObjectionKind.BAD_EXPERIENCE),
        ],
    )
    async def test_every_objection_kind_is_detected(
        self, utterance: str, kind: ObjectionKind
    ) -> None:
        llm = MockLLM(
            [
                {"next_utterance": "Understood.", "treatment_interest": "full_arch"},
                {"next_utterance": "I hear you.", "recovered": False},
            ]
        )
        convo = conversation(llm)
        await convo.start()
        await convo.say("full arch")
        await convo.say(utterance)
        assert convo.fields.objection(kind) is not None

    async def test_an_ordinary_answer_does_not_divert(self) -> None:
        llm = MockLLM(HOT_LEAD)
        convo = conversation(llm)
        await convo.start()
        await convo.say("i am missing my lower teeth")
        assert convo.state["current_node"] == SITUATION
        assert convo.fields.objections == []


class TestTerminalPaths:
    async def test_wrong_number_ends_the_call_without_qualifying(self) -> None:
        llm = MockLLM(
            [
                {
                    "next_utterance": "Sorry, you have reached a dental office.",
                    "treatment_interest": "wrong_number",
                }
            ]
        )
        convo = conversation(llm)
        await convo.start()
        await convo.say("i was calling the pharmacy")
        assert convo.finished
        assert convo.outcome == "wrong_number"
        assert convo.state["current_node"] == END_CALL

    async def test_a_cold_lead_is_routed_to_a_callback(self) -> None:
        llm = MockLLM(
            [
                {
                    "next_utterance": "One implant, understood.",
                    "treatment_interest": "single_implant",
                },
                {"next_utterance": "Any pain?", "pain_level": 1},
                {"next_utterance": "Insurance?", "has_insurance": False},
                {"next_utterance": "Your name?", "name": "Sam"},
            ]
        )
        convo = conversation(llm)
        await convo.start()
        for text in ["one implant", "no pain", "no insurance", "sam"]:
            spoken = await convo.say(text)
        assert convo.decision is Decision.CALLBACK
        assert convo.outcome == "callback_booked"
        assert any("call you back" in line for line in spoken)

    async def test_no_coordinator_sends_a_hot_lead_to_a_callback(self) -> None:
        llm = MockLLM(HOT_LEAD)
        convo = conversation(llm, coordinator_available=False)
        await convo.start()
        for text in ["full arch", "hurts", "yes", "bob"]:
            await convo.say(text)
        assert convo.state["score"] == 75
        assert convo.decision is Decision.CALLBACK
        assert convo.outcome == "callback_booked"

    async def test_the_threshold_moves_the_route(self) -> None:
        for threshold, expected in ((60, Decision.HANDOFF), (80, Decision.CALLBACK)):
            llm = MockLLM(list(HOT_LEAD))
            convo = conversation(llm, threshold=threshold)
            await convo.start()
            for text in ["full arch", "hurts", "yes", "bob"]:
                await convo.say(text)
            assert convo.decision is expected

    async def test_speaking_after_the_call_ends_does_nothing(self) -> None:
        llm = MockLLM([{"next_utterance": "Sorry.", "treatment_interest": "wrong_number"}])
        convo = conversation(llm)
        await convo.start()
        await convo.say("wrong number")
        assert await convo.say("hello?") == []


class TestFailureHandling:
    async def test_a_response_that_does_not_match_the_schema_raises(self) -> None:
        from arcagent.agent.llm import parse_or_raise
        from arcagent.agent.schemas import SituationOutput

        with pytest.raises(LLMError):
            parse_or_raise('{"next_utterance": "hi", "pain_level": 99}', SituationOutput)

    async def test_non_json_raises(self) -> None:
        from arcagent.agent.llm import parse_or_raise
        from arcagent.agent.schemas import TreatmentInterestOutput

        with pytest.raises(LLMError):
            parse_or_raise("I think they want a full arch", TreatmentInterestOutput)

    async def test_an_enum_value_outside_the_vocabulary_raises(self) -> None:
        from arcagent.agent.llm import parse_or_raise
        from arcagent.agent.schemas import TreatmentInterestOutput

        with pytest.raises(LLMError):
            parse_or_raise(
                '{"next_utterance": "ok", "treatment_interest": "dentures"}',
                TreatmentInterestOutput,
            )


class TestLatency:
    async def test_the_model_ttft_reaches_state_for_the_latency_column(self) -> None:
        llm = MockLLM(HOT_LEAD)
        convo = conversation(llm)
        await convo.start()
        await convo.say("full arch")
        assert convo.state["llm_ttft_s"] == pytest.approx(0.18)


class TestPromptVersioning:
    def test_a_missing_version_is_a_clear_error(self) -> None:
        from arcagent.agent.prompts import PromptNotFound, load_prompt

        with pytest.raises(PromptNotFound):
            load_prompt("system", "v99")

    def test_v1_exists_with_a_prompt_for_every_llm_node(self) -> None:
        from arcagent.agent.graph import LLM_NODES
        from arcagent.agent.prompts import available_versions, load_prompt

        assert "v1" in available_versions()
        for node in LLM_NODES:
            assert load_prompt(node, "v1")

    def test_the_v1_prompts_are_still_marked_for_the_owner(self) -> None:
        """A reminder that these are placeholders, not finished wording."""
        from arcagent.agent.graph import LLM_NODES
        from arcagent.agent.prompts import load_prompt

        assert all("TODO_OWNER" in load_prompt(node, "v1") for node in LLM_NODES)
