"""Recorded inputs, rather than mutable files, identify the benchmark being compared."""

import copy
import json

import pytest

from arcagent.config import Settings
from evals.persona import load_personas
from evals.snapshots import RunSnapshot, capture_snapshot
from tests.test_eval_harness import FIXTURES


def snapshot_payload(repeats: int = 1) -> dict:
    return capture_snapshot(
        load_personas(FIXTURES),
        Settings(_env_file=None),
        prompt_version="v1",
        threshold=60,
        repeats=repeats,
        concurrency=1,
        caller_model="test-caller",
    ).model_dump(mode="json")


def test_snapshot_keeps_complete_personas_and_effective_prompts_without_secrets() -> None:
    settings = Settings(_env_file=None, llm_api_key="do-not-record", database_url="secret-db")
    personas = load_personas(FIXTURES)
    snapshot = capture_snapshot(
        personas,
        settings,
        prompt_version="v1",
        threshold=65,
        repeats=2,
        concurrency=3,
        caller_model="caller-override",
    )
    raw = snapshot.model_dump(mode="json")
    personas[0].expected.fields.clear()
    assert raw["personas"]["fixture_hot"]["expected"]["fields"]
    assert snapshot.config.threshold == 65
    assert snapshot.config.caller_model == "caller-override"
    assert snapshot.config.repeats == 2
    assert snapshot.prompts["system"].content
    assert len(snapshot.prompts["system"].sha256) == 64
    assert snapshot.source_hashes["evals/metrics.py"]
    assert "do-not-record" not in json.dumps(raw)
    assert "secret-db" not in json.dumps(raw)
    assert RunSnapshot.model_validate(raw) == snapshot


def test_snapshot_rejects_altered_prompt_content() -> None:
    raw = copy.deepcopy(snapshot_payload())
    raw["prompts"]["system"]["content"] += " altered"
    with pytest.raises(ValueError, match="hash"):
        RunSnapshot.model_validate(raw)


@pytest.mark.parametrize("field", ["repeats", "concurrency"])
def test_snapshot_rejects_nonpositive_run_limits(field: str) -> None:
    raw = snapshot_payload()
    raw["config"][field] = 0
    with pytest.raises(ValueError):
        RunSnapshot.model_validate(raw)


async def test_text_entrypoint_records_inputs_before_calls_and_uses_availability(
    monkeypatch,
    ready_prompts,
) -> None:
    from argparse import Namespace

    from evals.run_text import run
    from tests.test_eval_harness import TestSummary

    settings = Settings(_env_file=None, llm_api_key="fixture", coordinator_available=False)
    personas = load_personas(FIXTURES)
    seen = []
    monkeypatch.setattr("evals.run_text.get_settings", lambda: settings)
    monkeypatch.setattr("evals.run_text.load_personas", lambda **kwargs: personas)

    async def fake_scenario(**kwargs):
        # Simulates the files/objects changing after the run starts.
        assert kwargs["coordinator_available"] is False
        kwargs["persona"].expected.fields.clear()
        return TestSummary()._result(scenario_id=kwargs["persona"].id)

    monkeypatch.setattr("evals.run_text.run_scenario", fake_scenario)

    def save(args, results, sha, snapshot):
        seen.append(snapshot)
        return 9

    monkeypatch.setattr("evals.run_text.write_results", save)
    args = Namespace(
        run_name="fixture",
        repeats=1,
        concurrency=1,
        groups=None,
        ids=None,
        caller_model="caller",
        prompts="v1",
        threshold=60,
        no_db=False,
    )
    assert await run(args) == 9
    assert seen[0].personas["fixture_hot"].expected.fields
    assert seen[0].config.coordinator_available is False


def test_snapshot_export_reads_saved_data_only(tmp_path, monkeypatch) -> None:
    from arcagent.persistence.db import get_engine, session_scope
    from arcagent.persistence.models import Base, Tier
    from arcagent.persistence.repo import EvalRepository
    from evals.snapshots import main

    url = f"sqlite:///{tmp_path / 'export.db'}"
    Base.metadata.create_all(get_engine(url))
    payload = snapshot_payload()
    with session_scope(url) as session:
        run = EvalRepository(session).create_run(
            "saved", "fixture-sha", "v1", 60, Tier.TEXT, snapshot=payload
        )
        run_id = run.id
    monkeypatch.setattr("arcagent.persistence.db.session_scope", lambda: session_scope(url))
    output = tmp_path / "inputs.json"
    monkeypatch.setattr("sys.argv", ["snapshots", str(run_id), "--output", str(output)])
    main()
    assert json.loads(output.read_text()) == {
        "run_id": run_id,
        "git_sha": "fixture-sha",
        "snapshot": payload,
    }
