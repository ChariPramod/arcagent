"""Offline lab contracts; expected behavior is authored independently of the simulator."""

import json
import subprocess
import sys

import pytest

from evals.replay import compare_replays, replay, scenario_catalog


@pytest.mark.parametrize(
    ("scenario", "required", "forbidden"),
    [
        ("silence", "offer_callback", "handoff"),
        ("interrupt", "clear_playback", "resume_cancelled_audio"),
        ("delayed_transcript", "discard_late_transcript", "respond_to_late_transcript"),
        ("vendor_timeout", "offer_callback", "retry_vendor"),
        ("disconnect", "cancel_pending_work", "send_after_disconnect"),
        ("unanswered_handoff", "offer_callback", "claim_transfer_success"),
    ],
)
def test_scenarios_have_safe_default_outcomes(scenario, required, forbidden):
    result = replay({"scenario_id": scenario})
    actions = [action["type"] for action in result["actions"]]
    assert required in actions
    assert forbidden not in actions
    assert result["passed"] is True
    assert result["simulated"] is True
    assert result == replay({"scenario_id": scenario})
    assert result["events"] == sorted(result["events"], key=lambda event: event["at_ms"])


@pytest.mark.parametrize(
    "config",
    [
        {"vendor_timeout_ms": True},
        {"handoff_threshold": 101},
        {"transcript_timeout_ms": 0},
        {"extra": 1},
        {"vendor_timeout_ms": float("inf")},
    ],
)
def test_invalid_configs_are_rejected(config):
    with pytest.raises(ValueError):
        replay({"scenario_id": "silence", "config": config})


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"scenario_id": "unknown"},
        {"scenario_id": "silence", "events": []},
        {"scenario_id": "silence", "config": None},
    ],
)
def test_invalid_requests_are_rejected(payload):
    with pytest.raises(ValueError):
        replay(payload)


def test_timeout_counterfactual_exposes_failed_expectation():
    result = compare_replays(
        {"scenario_id": "delayed_transcript", "candidate_config": {"transcript_timeout_ms": 4000}}
    )
    assert result["baseline"]["passed"] is True
    assert result["candidate"]["passed"] is False
    assert "accept_transcript" in [a["type"] for a in result["candidate"]["actions"]]
    assert result["changes"]


def test_threshold_uses_real_scoring():
    result = compare_replays(
        {"scenario_id": "unanswered_handoff", "candidate_config": {"handoff_threshold": 100}}
    )
    assert result["baseline"]["metrics"]["score"] == 65
    assert result["baseline"]["metrics"]["route"] == "handoff"
    assert result["candidate"]["metrics"]["route"] == "callback"
    assert result["candidate"]["passed"] is False


def test_catalog_returns_independent_data():
    catalog = scenario_catalog()
    catalog[0]["title"] = "changed"
    assert scenario_catalog()[0]["title"] != "changed"


def test_cli_refuses_overwrite_and_fails_bad_counterfactual(tmp_path):
    artifact = tmp_path / "report.json"
    command = [sys.executable, "-m", "scripts.run_failure_lab", "--output", str(artifact)]
    assert subprocess.run(command, capture_output=True).returncode == 0
    original = artifact.read_bytes()
    assert len(json.loads(original)["results"]) == 6
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert artifact.read_bytes() == original
    failed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.run_failure_lab",
            "--scenario",
            "delayed_transcript",
            "--transcript-timeout-ms",
            "4000",
        ],
        capture_output=True,
    )
    assert failed.returncode == 1
    assert json.loads(failed.stdout)["passed"] is False


def test_transcript_at_deadline_expires_before_arrival():
    result = replay(
        {"scenario_id": "delayed_transcript", "config": {"transcript_timeout_ms": 3000}}
    )
    assert result["actions"] == [
        {"at_ms": 3000, "type": "ask_to_repeat"},
        {"at_ms": 3000, "type": "discard_late_transcript"},
    ]


def test_interrupt_cancels_generation_before_clearing_playback():
    result = replay({"scenario_id": "interrupt"})
    assert [a["type"] for a in result["actions"]] == [
        "cancel_generation",
        "clear_playback",
        "discard_cancelled_audio",
    ]


def test_counterfactual_timeout_changes_simulated_duration_only():
    result = compare_replays(
        {"scenario_id": "vendor_timeout", "candidate_config": {"vendor_timeout_ms": 100}}
    )
    assert result["baseline"]["metrics"]["duration_ms"] == 2000
    assert result["candidate"]["metrics"]["duration_ms"] == 100
    assert result["candidate"]["passed"] is True
    assert "simulated transport and timing" in result["candidate"]["provenance"]


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"scenario_id": "silence", "extra": True},
        {"scenario_id": "silence", "candidate_config": None},
    ],
)
def test_comparison_validation(payload):
    with pytest.raises(ValueError):
        compare_replays(payload)
