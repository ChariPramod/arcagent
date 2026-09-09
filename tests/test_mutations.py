"""Offline tests of mutation generation and scoring, not model quality measurements."""

import copy
from argparse import Namespace

import pytest

from arcagent.config import Settings
from evals.mutations import ScriptedCaller, load_cases, run, run_cases
from evals.simulator import CallerTurn
from evals.snapshots import RunSnapshot, capture_snapshot
from tests.test_eval_harness import ScriptedEvalLLM


def test_delivery_mutations_preserve_expected_answers_and_are_isolated() -> None:
    cases = load_cases()
    assert len(cases) == 10
    assert len({case.persona.id for case in cases}) == len(cases)
    for prefix in ("mutation_hot", "mutation_price"):
        family = [case for case in cases if case.persona.id.startswith(prefix)]
        assert len({tuple(case.utterances) for case in family}) == 5
        assert all(case.persona.expected == family[0].persona.expected for case in family)
    before = copy.deepcopy(cases[1].persona.expected.fields)
    cases[0].persona.expected.fields.clear()
    assert cases[1].persona.expected.fields == before


async def test_scripted_caller_finishes_and_does_not_mutate_the_fixture() -> None:
    lines = ["hello", "goodbye"]
    caller = ScriptedCaller(lines)
    turns = [(await caller.complete("", [], CallerTurn)).parsed for _ in range(3)]
    assert [turn.utterance for turn in turns] == ["hello", "goodbye", ""]
    assert [turn.hung_up for turn in turns] == [False, False, True]
    assert lines == ["hello", "goodbye"]


@pytest.mark.parametrize("correct", [True, False])
async def test_each_variant_is_scored_against_ground_truth_not_just_consistency(correct) -> None:
    cases = [case for case in load_cases() if case.persona.group == "hot_buyers"]
    outputs = [
        {
            "next_utterance": "Tell me more.",
            "treatment_interest": "full_arch" if correct else "single_implant",
        },
        {"next_utterance": "Insurance?", "pain_level": 8},
        {"next_utterance": "Contact?", "has_insurance": True},
        {"next_utterance": "Thank you.", "name": "Test Caller", "callback_number": "2025550123"},
    ]
    llm = ScriptedEvalLLM(agent=outputs * len(cases) * 2, caller=[])
    results = await run_cases(
        cases, llm, repeats=2, prompt_version="v1", threshold=60, coordinator_available=True
    )
    assert len(results) == len(cases) * 2
    assert all(result.passed is correct for result in results)
    if not correct:
        assert all("treatment_interest" in result.missed_fields for result in results)
    for result in results:
        case = next(case for case in cases if case.persona.id == result.scenario_id)
        assert [
            text for speaker, text in result.transcript if speaker == "caller"
        ] == case.utterances


def test_mutation_snapshot_contains_the_exact_scripts() -> None:
    cases = load_cases()
    snapshot = capture_snapshot(
        [case.persona for case in cases],
        Settings(_env_file=None),
        prompt_version="v1",
        threshold=60,
        repeats=1,
        concurrency=1,
        caller_model="scripted-caller-v1",
        suite="fixture_mutations",
        caller_scripts={case.persona.id: case.utterances for case in cases},
    )
    restored = RunSnapshot.model_validate(snapshot.model_dump(mode="json"))
    assert restored.suite == "fixture_mutations"
    assert restored.caller_scripts[cases[0].persona.id] == cases[0].utterances


async def test_list_runs_without_keys_database_or_model(monkeypatch, capsys) -> None:
    monkeypatch.setattr("evals.mutations.get_settings", lambda: Settings(_env_file=None))
    assert await run(Namespace(list=True)) == 0
    assert "mutation_hot__self_correction" in capsys.readouterr().out


async def test_failed_mutations_return_nonzero_and_save_the_suite_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        "evals.mutations.get_settings", lambda: Settings(_env_file=None, llm_api_key="fixture")
    )
    monkeypatch.setattr(
        "evals.mutations.AnthropicStructuredLLM", lambda _: ScriptedEvalLLM(agent=[], caller=[])
    )
    saved = []

    def save(args, results, sha, snapshot):
        saved.append((results, snapshot))
        return 1

    monkeypatch.setattr("evals.mutations.write_results", save)
    args = Namespace(
        list=False, run_name="fixture", repeats=1, prompts="v1", threshold=60, no_db=False
    )
    assert await run(args) == 1
    assert len(saved[0][0]) == 10
    assert saved[0][1].suite == "fixture_mutations"
