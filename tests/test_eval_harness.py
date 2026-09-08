"""The eval harness: persona loading, metric definitions, and the runner.

Fixture personas live in tests/fixtures/personas so the owner authored evals/personas
directory is never touched by a test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arcagent.agent.llm import LLMResult
from evals import metrics
from evals.persona import PersonaError, PersonaGroup, load_persona, load_personas
from evals.runner import format_summary, run_scenario, summarise
from evals.simulator import SimulatedCaller

FIXTURES = Path(__file__).parent / "fixtures" / "personas"


class TestPersonaLoading:
    def test_a_valid_persona_loads(self) -> None:
        persona = load_persona(FIXTURES / "fixture_hot.yaml")
        assert persona.id == "fixture_hot"
        assert persona.group is PersonaGroup.HOT_BUYERS
        assert persona.expected.handoff
        assert persona.behaviour.withholds == ["employer_name"]

    def test_underscore_files_are_skipped(self) -> None:
        """Otherwise the template would be run as if it were a scenario."""
        ids = {p.id for p in load_personas(FIXTURES)}
        assert "ignored" not in ids
        assert ids == {"fixture_hot", "fixture_price"}

    def test_personas_come_back_sorted_so_runs_are_comparable(self) -> None:
        assert [p.id for p in load_personas(FIXTURES)] == ["fixture_hot", "fixture_price"]

    def test_filtering_by_group(self) -> None:
        assert [p.id for p in load_personas(FIXTURES, groups=["price_objectors"])] == [
            "fixture_price"
        ]

    def test_filtering_by_id(self) -> None:
        assert [p.id for p in load_personas(FIXTURES, ids=["fixture_hot"])] == ["fixture_hot"]

    def test_an_unknown_field_is_an_error_not_a_silent_ignore(self, tmp_path: Path) -> None:
        """A typo in a persona must fail the run, not silently change what is tested."""
        path = tmp_path / "typo.yaml"
        path.write_text(
            "id: typo\ngroup: hot_buyers\ndescription: d\nbackground: b\n"
            "expected:\n  outcome: handoff\ncallbak_response: accepts\n"
        )
        with pytest.raises(PersonaError):
            load_persona(path)

    def test_an_unknown_group_is_an_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad_group.yaml"
        path.write_text(
            "id: x\ngroup: made_up\ndescription: d\nbackground: b\nexpected:\n  outcome: handoff\n"
        )
        with pytest.raises(PersonaError):
            load_persona(path)

    def test_malformed_yaml_is_an_error(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.yaml"
        path.write_text("id: [unclosed\n")
        with pytest.raises(PersonaError):
            load_persona(path)

    def test_duplicate_ids_are_rejected(self, tmp_path: Path) -> None:
        for name in ("a.yaml", "b.yaml"):
            (tmp_path / name).write_text(
                "id: same\ngroup: hot_buyers\ndescription: d\nbackground: b\n"
                "expected:\n  outcome: handoff\n"
            )
        with pytest.raises(PersonaError, match="duplicate"):
            load_personas(tmp_path)

    def test_the_owner_directory_holds_no_agent_written_personas_yet(self) -> None:
        """Guards the rule that personas are owner authored. Update when the owner writes them."""
        from evals.persona import PERSONAS_DIR

        real = [p for p in PERSONAS_DIR.glob("*.yaml") if not p.name.startswith("_")]
        assert real == [] or len(real) == 30, (
            "evals/personas should be empty until the owner writes all thirty"
        )


class TestFieldAccuracy:
    def test_all_correct_is_one(self) -> None:
        result = metrics.field_accuracy(
            {"treatment_interest": "full_arch", "pain_level": 8},
            {"treatment_interest": "full_arch", "pain_level": 8},
        )
        assert result.accuracy == 1.0
        assert result.missed == ()

    def test_a_wrong_field_is_named(self) -> None:
        result = metrics.field_accuracy(
            {"treatment_interest": "full_arch", "pain_level": 8},
            {"treatment_interest": "single_implant", "pain_level": 8},
        )
        assert result.accuracy == 0.5
        assert result.missed == ("treatment_interest",)

    def test_a_missing_field_counts_as_wrong(self) -> None:
        result = metrics.field_accuracy({"pain_level": 8}, {})
        assert result.accuracy == 0.0

    def test_fields_the_caller_never_mentioned_are_excluded_not_counted_wrong(self) -> None:
        """Counting them would punish the agent for information that was never said."""
        result = metrics.field_accuracy(
            {"treatment_interest": "full_arch", "plan_type": "PPO"},
            {"treatment_interest": "full_arch"},
            not_expected=["plan_type"],
        )
        assert result.accuracy == 1.0
        assert result.excluded == ("plan_type",)
        assert result.total_compared == 1

    def test_strings_compare_case_and_whitespace_insensitively(self) -> None:
        result = metrics.field_accuracy(
            {"employer_name": "Acme Logistics"}, {"employer_name": "  acme   logistics "}
        )
        assert result.accuracy == 1.0

    def test_phone_numbers_compare_on_digits_only(self) -> None:
        assert metrics.field_matches("callback_number", "+1 (415) 555-0123", "4155550123")
        assert not metrics.field_matches("callback_number", "4155550123", "4155550124")

    def test_an_empty_phone_number_never_matches(self) -> None:
        assert not metrics.field_matches("callback_number", "", "")

    def test_no_expected_fields_is_full_marks_not_a_divide_by_zero(self) -> None:
        assert metrics.field_accuracy({}, {}).accuracy == 1.0


class TestHandoffMetrics:
    def test_a_perfect_run(self) -> None:
        counts = metrics.handoff_counts([(True, True), (False, False)])
        assert counts.precision == 1.0
        assert counts.recall == 1.0

    def test_a_false_handoff_costs_precision_not_recall(self) -> None:
        """A false handoff wastes a coordinator's time."""
        counts = metrics.handoff_counts([(True, True), (False, True)])
        assert counts.precision == 0.5
        assert counts.recall == 1.0

    def test_a_missed_handoff_costs_recall_not_precision(self) -> None:
        """A missed handoff loses a hot lead. This is the one the merge rule protects."""
        counts = metrics.handoff_counts([(True, False), (True, True)])
        assert counts.precision == 1.0
        assert counts.recall == 0.5

    def test_no_handoffs_expected_or_made_is_not_a_zero_division(self) -> None:
        counts = metrics.handoff_counts([(False, False)])
        assert counts.precision == 1.0
        assert counts.recall == 1.0
        assert counts.f1 == 1.0


class TestFallbackActivation:
    def test_firing_where_expected_and_nowhere_else(self) -> None:
        rates = metrics.fallback_activation([(True, True), (False, False)])
        assert rates["true_activation_rate"] == 1.0
        assert rates["false_activation_rate"] == 0.0

    def test_firing_on_a_scenario_with_no_objection_is_reported_separately(self) -> None:
        rates = metrics.fallback_activation([(False, True), (False, False)])
        assert rates["false_activation_rate"] == 0.5


class TestCrmCompleteness:
    def test_a_full_record(self) -> None:
        actual = {"treatment_interest": "full_arch", "name": "Bob", "callback_number": "415"}
        assert metrics.crm_completeness(actual) == 1.0

    def test_a_lead_with_no_number_is_two_thirds_complete(self) -> None:
        actual = {"treatment_interest": "full_arch", "name": "Bob", "callback_number": None}
        assert metrics.crm_completeness(actual) == pytest.approx(2 / 3)

    def test_an_empty_string_counts_as_missing(self) -> None:
        actual = {"treatment_interest": "full_arch", "name": "", "callback_number": "415"}
        assert metrics.crm_completeness(actual) == pytest.approx(2 / 3)


class TestSpreadAndFlakiness:
    def test_a_single_value_has_no_spread_and_is_not_an_error(self) -> None:
        s = metrics.spread([0.8])
        assert s.mean == 0.8
        assert s.stdev == 0.0
        assert s.n == 1

    def test_the_spread_is_reported_with_the_mean(self) -> None:
        s = metrics.spread([0.6, 0.8, 1.0])
        assert s.mean == pytest.approx(0.8)
        assert s.stdev > 0
        assert "+/-" in str(s)

    def test_a_scenario_that_flips_between_repeats_is_flaky(self) -> None:
        flaky = metrics.flaky_scenarios({"a": [True, False, True], "b": [True, True, True]})
        assert flaky == ["a"]

    def test_consistent_failures_are_not_flaky(self) -> None:
        """A scenario that always fails is a bug, not flakiness. They are different problems."""
        assert metrics.flaky_scenarios({"a": [False, False]}) == []

    def test_percentiles(self) -> None:
        values = [10.0, 20.0, 30.0, 40.0, 100.0]
        assert metrics.percentile(values, 50) == 30.0
        assert metrics.percentile(values, 95) == 100.0
        assert metrics.percentile([], 50) == 0.0


class ScriptedEvalLLM:
    """Plays both sides: the agent's node calls and the simulated caller's turns."""

    def __init__(self, agent: list[dict], caller: list[dict]) -> None:
        self.agent = list(agent)
        self.caller = list(caller)

    async def complete(self, system, messages, schema, model=None) -> LLMResult:
        queue = self.caller if schema.__name__ == "CallerTurn" else self.agent
        payload = queue.pop(0) if queue else self._default(schema)
        return LLMResult(
            parsed=schema.model_validate(payload), ttft_s=0.1, total_s=0.3, raw=json.dumps(payload)
        )

    @staticmethod
    def _default(schema) -> dict:
        if schema.__name__ == "CallerTurn":
            return {"utterance": "", "hung_up": True}
        return {"next_utterance": "go on"}


class TestRunScenario:
    async def test_a_hot_persona_that_is_extracted_correctly_passes(self) -> None:
        persona = load_persona(FIXTURES / "fixture_hot.yaml")
        llm = ScriptedEvalLLM(
            agent=[
                {"next_utterance": "Understood.", "treatment_interest": "full_arch"},
                {"next_utterance": "How bad is the pain?", "pain_level": 8},
                {"next_utterance": "Insurance?", "has_insurance": True},
                {"next_utterance": "Your name?", "name": "Bob", "callback_number": "4155550123"},
            ],
            caller=[
                {"utterance": "all my top teeth"},
                {"utterance": "pretty bad"},
                {"utterance": "yeah through work"},
                {"utterance": "bob"},
                {"utterance": "", "hung_up": True},
            ],
        )
        result = await run_scenario(persona, llm, llm)
        assert result.passed
        assert result.field_accuracy == 1.0
        assert result.outcome_actual == "handoff"
        assert result.handoff_actual
        assert result.crm_completeness == 1.0
        assert result.transcript

    async def test_a_wrong_extraction_fails_and_names_the_field(self) -> None:
        persona = load_persona(FIXTURES / "fixture_hot.yaml")
        llm = ScriptedEvalLLM(
            agent=[
                {"next_utterance": "Understood.", "treatment_interest": "single_implant"},
                {"next_utterance": "Pain?", "pain_level": 8},
                {"next_utterance": "Insurance?", "has_insurance": True},
                {"next_utterance": "Name?", "name": "Bob", "callback_number": "4155550123"},
            ],
            caller=[{"utterance": "teeth"} for _ in range(4)]
            + [{"utterance": "", "hung_up": True}],
        )
        result = await run_scenario(persona, llm, llm)
        assert not result.passed
        assert "treatment_interest" in result.missed_fields

    async def test_a_caller_who_hangs_up_ends_the_scenario(self) -> None:
        persona = load_persona(FIXTURES / "fixture_price.yaml")
        llm = ScriptedEvalLLM(
            agent=[{"next_utterance": "Understood.", "treatment_interest": "single_implant"}],
            caller=[{"utterance": "one implant"}, {"utterance": "", "hung_up": True}],
        )
        result = await run_scenario(persona, llm, llm)
        assert result.turns >= 1
        assert result.outcome_actual != "handoff"

    async def test_a_model_failure_is_recorded_not_swallowed(self) -> None:
        from arcagent.agent.llm import LLMError

        class FailingLLM:
            async def complete(self, system, messages, schema, model=None):
                raise LLMError("model unavailable")

        persona = load_persona(FIXTURES / "fixture_hot.yaml")
        result = await run_scenario(persona, FailingLLM(), FailingLLM())
        assert not result.passed
        assert result.error == "model unavailable"


class TestSummary:
    def _result(self, **overrides):
        from evals.runner import ScenarioResult

        base = dict(
            scenario_id="s1",
            group="hot_buyers",
            repeat_index=0,
            expected={},
            actual={},
            passed=True,
            field_accuracy=1.0,
            handoff_expected=True,
            handoff_actual=True,
            fallback_activated=False,
            outcome_expected="handoff",
            outcome_actual="handoff",
            handle_time_s=4.0,
            turns=6,
            crm_completeness=1.0,
        )
        return ScenarioResult(**(base | overrides))

    def test_an_empty_run_summarises_to_zero_not_a_crash(self) -> None:
        assert summarise([], repeats=3).pass_rate == 0.0

    def test_pass_rate_counts_every_repeat(self) -> None:
        results = [
            self._result(repeat_index=0, passed=True),
            self._result(repeat_index=1, passed=False),
        ]
        summary = summarise(results, repeats=2)
        assert summary.scenarios == 1
        assert summary.pass_rate == 0.5

    def test_a_scenario_that_flips_is_reported_as_flaky(self) -> None:
        results = [
            self._result(repeat_index=0, passed=True),
            self._result(repeat_index=1, passed=False),
        ]
        assert summarise(results, repeats=2).flaky == ["s1"]

    def test_metrics_are_broken_down_by_group(self) -> None:
        results = [
            self._result(scenario_id="a", group="hot_buyers"),
            self._result(
                scenario_id="b",
                group="price_objectors",
                passed=False,
                handoff_expected=False,
                handoff_actual=False,
                outcome_expected="callback_booked",
                outcome_actual="callback_booked",
            ),
        ]
        summary = summarise(results, repeats=1)
        assert set(summary.by_group) == {"hot_buyers", "price_objectors"}
        assert summary.by_group["hot_buyers"]["pass_rate"] == 1.0
        assert summary.by_group["price_objectors"]["pass_rate"] == 0.0

    def test_the_printed_summary_reports_spread_not_a_bare_number(self) -> None:
        text = format_summary(summarise([self._result()], repeats=1), "baseline", 7)
        assert "+/-" in text
        assert "handoff precision" in text
        assert "flaky scenarios" in text


class TestSimulatorPrompt:
    def test_the_caller_is_told_to_volunteer_nothing(self) -> None:
        persona = load_persona(FIXTURES / "fixture_hot.yaml")
        prompt = SimulatedCaller(persona=persona, llm=None).system_prompt()
        assert "Do not be helpful" in prompt
        assert "Answer only what was asked" in prompt

    def test_withheld_fields_reach_the_prompt(self) -> None:
        persona = load_persona(FIXTURES / "fixture_hot.yaml")
        prompt = SimulatedCaller(persona=persona, llm=None).system_prompt()
        assert "employer_name" in prompt
        assert "not give these up the first time" in prompt.lower()

    def test_objections_and_their_recovery_reach_the_prompt(self) -> None:
        persona = load_persona(FIXTURES / "fixture_price.yaml")
        prompt = SimulatedCaller(persona=persona, llm=None).system_prompt()
        assert "price objection" in prompt
        assert "never drop it" in prompt.lower()

    def test_the_simulator_is_never_told_what_is_expected(self) -> None:
        """Telling it the expected fields would make the eval measure nothing."""
        persona = load_persona(FIXTURES / "fixture_hot.yaml")
        prompt = SimulatedCaller(persona=persona, llm=None).system_prompt()
        assert "handoff" not in prompt.lower()
        assert "pain_level" not in prompt


class TestPhoneComparison:
    """A number is the same number however it was written down."""

    @pytest.mark.parametrize(
        ("expected", "actual"),
        [
            ("+1 (415) 555-0123", "4155550123"),
            ("4155550123", "+14155550123"),
            ("415-555-0123", "415.555.0123"),
            ("(415) 555 0123", "14155550123"),
        ],
    )
    def test_equivalent_forms_match(self, expected: str, actual: str) -> None:
        assert metrics.field_matches("callback_number", expected, actual)

    @pytest.mark.parametrize(
        ("expected", "actual"),
        [
            ("4155550123", "4155550124"),
            ("4155550123", None),
            ("4155550123", ""),
            ("", "4155550123"),
        ],
    )
    def test_different_numbers_do_not_match(self, expected: str, actual: str | None) -> None:
        assert not metrics.field_matches("callback_number", expected, actual)
