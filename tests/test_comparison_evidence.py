"""A green merge verdict requires comparable benchmark evidence."""

import copy
from types import SimpleNamespace

import pytest

from arcagent.persistence.models import Tier
from evals.compare_runs import InvalidComparison, comparison_groups
from tests.test_eval_snapshots import snapshot_payload


def evidence():
    snapshot = snapshot_payload(repeats=2)
    run = SimpleNamespace(
        id=1, tier=Tier.TEXT, prompt_version="v1", threshold=60, snapshot=snapshot
    )
    rows = [
        SimpleNamespace(
            scenario_id=key,
            repeat_index=repeat,
            passed=True,
            expected=copy.deepcopy(persona["expected"]["fields"]),
            handoff_expected=persona["expected"]["handoff"],
            handoff_actual=persona["expected"]["handoff"],
            field_accuracy=1.0,
            crm_completeness=1.0,
            notes=None,
        )
        for key, persona in snapshot["personas"].items()
        for repeat in range(2)
    ]
    return run, rows


def test_comparison_uses_snapshot_even_when_persona_files_are_unavailable(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("comparison must not read mutable persona files")

    monkeypatch.setattr("evals.persona.load_personas", forbidden)
    old, rows = evidence()
    assert comparison_groups(old, copy.deepcopy(old), rows, copy.deepcopy(rows)) == {
        "fixture_hot": "hot_buyers",
        "fixture_price": "price_objectors",
    }


@pytest.mark.parametrize(
    "damage",
    [
        "legacy",
        "empty",
        "missing_repeat",
        "duplicate",
        "extra_scenario",
        "audio",
        "changed_persona",
        "changed_category",
        "changed_expected",
        "changed_row_expected",
        "missing_metric",
        "invalid_metric",
        "missing_handoff",
        "error",
        "changed_caller",
        "changed_availability",
        "changed_repeats",
        "metadata_mismatch",
        "malformed",
        "missing_guarded_category",
        "no_expected_handoff",
    ],
)
def test_invalid_evidence_never_approves_a_comparison(damage: str) -> None:
    old, old_rows = evidence()
    new, rows = copy.deepcopy(old), copy.deepcopy(old_rows)
    if damage == "legacy":
        new.snapshot = None
    elif damage == "empty":
        rows.clear()
    elif damage == "missing_repeat":
        rows.pop()
    elif damage == "duplicate":
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == "extra_scenario":
        rows[0].scenario_id = "unknown"
    elif damage == "audio":
        new.tier = Tier.AUDIO
    elif damage == "changed_persona":
        new.snapshot["personas"]["fixture_hot"]["background"] = "Changed caller"
    elif damage == "changed_category":
        new.snapshot["personas"]["fixture_price"]["group"] = "logistics"
    elif damage == "changed_expected":
        new.snapshot["personas"]["fixture_hot"]["expected"]["outcome"] = "callback_booked"
    elif damage == "changed_row_expected":
        rows[0].expected = {}
    elif damage == "missing_metric":
        rows[0].field_accuracy = None
    elif damage == "invalid_metric":
        rows[0].crm_completeness = float("nan")
    elif damage == "missing_handoff":
        rows[0].handoff_actual = None
    elif damage == "error":
        rows[0].notes = "model unavailable"
    elif damage == "changed_caller":
        new.snapshot["config"]["caller_model"] = "different-caller"
    elif damage == "changed_availability":
        new.snapshot["config"]["coordinator_available"] = False
    elif damage == "changed_repeats":
        new.snapshot["config"]["repeats"] = 1
        rows = [row for row in rows if row.repeat_index == 0]
    elif damage == "metadata_mismatch":
        new.threshold = 75
    elif damage == "malformed":
        new.snapshot = {"schema_version": 99}
    elif damage == "missing_guarded_category":
        del new.snapshot["personas"]["fixture_price"]
        rows = [row for row in rows if row.scenario_id != "fixture_price"]
    elif damage == "no_expected_handoff":
        new.snapshot["personas"]["fixture_hot"]["expected"]["handoff"] = False
        for row in rows:
            row.handoff_expected = False
    with pytest.raises(InvalidComparison):
        comparison_groups(old, new, old_rows, rows)


def test_prompt_and_threshold_changes_are_comparable_and_keep_the_benchmark() -> None:
    from evals.snapshots import content_hash

    old, rows = evidence()
    new = copy.deepcopy(old)
    new.threshold = new.snapshot["config"]["threshold"] = 70
    new.prompt_version = new.snapshot["config"]["prompt_version"] = "v2"
    new.snapshot["prompts"]["system"] = {
        "content": "new prompt",
        "sha256": content_hash("new prompt"),
    }
    assert comparison_groups(old, new, rows, copy.deepcopy(rows))


def test_fixture_suite_cannot_be_compared_with_owner_benchmark() -> None:
    old, rows = evidence()
    new = copy.deepcopy(old)
    new.snapshot["suite"] = "fixture_mutations"
    new.snapshot["caller_scripts"] = {key: ["fixture"] for key in new.snapshot["personas"]}
    with pytest.raises(InvalidComparison, match="suite changed"):
        comparison_groups(old, new, rows, copy.deepcopy(rows))


@pytest.mark.parametrize("key", ["schema_version", "suite", "runtime", "source_hashes"])
def test_incomplete_snapshot_is_rejected(key: str) -> None:
    old, rows = evidence()
    new = copy.deepcopy(old)
    del new.snapshot[key]
    with pytest.raises(InvalidComparison, match="malformed input snapshot"):
        comparison_groups(old, new, rows, copy.deepcopy(rows))


def test_legacy_run_cli_returns_invalid_instead_of_a_green_verdict(
    tmp_path, monkeypatch, capsys
) -> None:
    from arcagent.persistence.db import get_engine, session_scope
    from arcagent.persistence.models import Base
    from arcagent.persistence.repo import EvalRepository
    from evals.compare_runs import compare

    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    Base.metadata.create_all(get_engine(url))
    with session_scope(url) as session:
        repo = EvalRepository(session)
        old = repo.create_run("before", "sha", "v1", 60, Tier.TEXT)
        new = repo.create_run("after", "sha", "v1", 60, Tier.TEXT)
        ids = old.id, new.id
    monkeypatch.setattr("evals.compare_runs.session_scope", lambda: session_scope(url))
    assert compare(*ids) == 2
    output = capsys.readouterr().out
    assert "COMPARISON INVALID" in output
    assert "no guarded metric regressed" not in output
