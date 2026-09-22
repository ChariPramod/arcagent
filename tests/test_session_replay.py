"""The replay executes the production session with bounded offline dependencies."""

import pytest

from evals.session_replay import compare_sessions, replay_session


@pytest.mark.parametrize("scenario", ["interrupt", "disconnect", "vendor_failure"])
async def test_production_session_replay(scenario):
    result = await replay_session({"version": 1, "scenario_id": scenario})
    assert len(result["implementation_sha256"]) == 64
    assert result["passed"]
    assert result["implementation"] == "arcagent.telephony.call_session.CallSession"
    assert result == await replay_session({"version": 1, "scenario_id": scenario})
    assert result["timing"] == "synthetic clock; latency not measured"


async def test_counterfactual_changes_actual_interruption():
    result = await compare_sessions(
        {"version": 1, "scenario_id": "interrupt", "candidate_config": {"barge_in_min_words": 4}}
    )
    assert result["baseline"]["passed"]
    assert not result["candidate"]["passed"]
    assert result["baseline"]["observed"]["barge_ins"] == 1
    assert result["candidate"]["observed"]["barge_ins"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"version": 2, "scenario_id": "interrupt"},
        {"version": True, "scenario_id": "interrupt"},
        {"version": 1, "scenario_id": "unknown"},
        {"version": 1, "scenario_id": "interrupt", "config": {"barge_in_min_words": True}},
        {"version": 1, "scenario_id": "interrupt", "config": {"barge_in_min_words": 100}},
        {"version": 1, "scenario_id": "interrupt", "events": []},
    ],
)
async def test_invalid_input_rejected(payload):
    with pytest.raises(ValueError):
        await replay_session(payload)


def test_cli_json_and_nonzero_comparison(tmp_path):
    import json
    import subprocess
    import sys

    command = [sys.executable, "-m", "scripts.run_session_replay"]
    result = subprocess.run(command, capture_output=True, timeout=10)
    assert result.returncode == 0
    assert len(json.loads(result.stdout)["results"]) == 3
    result = subprocess.run(
        [*command, "--scenario", "interrupt", "--candidate-barge-in-min-words", "4"],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert not json.loads(result.stdout)["passed"]
    artifact = tmp_path / "existing.json"
    artifact.write_text("keep")
    result = subprocess.run([*command, "--output", str(artifact)], capture_output=True, timeout=10)
    assert result.returncode == 2
    assert artifact.read_text() == "keep"


async def test_external_cancellation_leaves_no_session_tasks():
    import asyncio

    task = asyncio.create_task(replay_session({"version": 1, "scenario_id": "interrupt"}))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not any(
        task.get_name() == "offline-session-replay" and not task.done()
        for task in asyncio.all_tasks()
    )
