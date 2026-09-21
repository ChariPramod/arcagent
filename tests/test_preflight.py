"""Offline readiness reports fixture contents without credentials or vendor work."""

import json

import pytest

from arcagent.agent import prompts
from evals import preflight


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    root = tmp_path / "prompts"
    version = root / "v2"
    version.mkdir(parents=True)
    from arcagent.agent.readiness import REQUIRED_PROMPTS

    for name in REQUIRED_PROMPTS:
        (version / f"{name}.md").write_text("Reviewed synthetic test instruction.")
    monkeypatch.setattr(prompts, "PROMPTS_ROOT", root)
    prompts.load_prompt.cache_clear()
    personas = tmp_path / "personas"
    personas.mkdir()
    (personas / "example.yaml").write_text("""id: example
group: hot_buyers
description: Synthetic fixture
background: Fictional caller
expected:
  outcome: handoff
  handoff: true
""")
    yield version, personas
    prompts.load_prompt.cache_clear()


def test_preflight_reports_complete_inputs_without_keys(inputs, capsys):
    _, personas = inputs
    assert preflight.main(["--prompts", "v2", "--personas-dir", str(personas), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is True
    assert report["persona_count"] == 1
    assert report["groups"] == {"hot_buyers": 1}
    assert report["issues"] == []


def test_preflight_reports_placeholder_and_empty_selection(inputs, capsys):
    version, personas = inputs
    (version / "system.md").write_text("TODO_OWNER: private-content-must-not-print")
    assert (
        preflight.main(
            ["--prompts", "v2", "--personas-dir", str(personas), "--ids", "absent", "--json"]
        )
        == 2
    )
    raw = capsys.readouterr().out
    assert "private-content" not in raw
    report = json.loads(raw)
    assert report["ready"] is False
    assert {"component": "prompts", "name": "system", "reason": "placeholder"} in report["issues"]
    assert {"component": "personas", "name": "suite", "reason": "no_selected_personas"} in report[
        "issues"
    ]


def test_preflight_sanitizes_invalid_persona_values(inputs, capsys):
    _, personas = inputs
    (personas / "example.yaml").write_text("background: private-caller-secret")
    assert preflight.main(["--prompts", "v2", "--personas-dir", str(personas), "--json"]) == 2
    raw = capsys.readouterr().out
    assert "private-caller-secret" not in raw
    assert json.loads(raw)["issues"] == [
        {"component": "personas", "name": "suite", "reason": "invalid_personas"}
    ]
