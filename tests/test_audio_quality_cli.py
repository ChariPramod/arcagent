"""Audio CLI quality gates: successful transport alone must never pass a release check.

The scenario result is the orchestration seam. Real audio/socket integration is exercised
elsewhere; these tests run the real CLI, grading and SQLite persistence without vendors.
"""

import sys
from argparse import Namespace

import pytest
from sqlalchemy import func, select

from arcagent.config import Settings
from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import Base, EvalResult, EvalRun, Tier
from evals import run_audio
from evals.persona import Expected, Persona
from tests.fakes import FakeTtsSocket


@pytest.fixture
def quality_cli(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'quality.db'}"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    settings = Settings(
        _env_file=None,
        database_url=url,
        audio_eval_token="fixture-token",
        cartesia_api_key="fixture-tts",
        cartesia_voice_id="fixture-agent-voice",
        llm_api_key="fixture-llm",
    )
    expected = Expected(outcome="handoff", handoff=True, fields={"name": "Pat"})
    persona = Persona(
        id="quality-fixture",
        group="hot_buyers",
        description="Synthetic CLI quality fixture",
        background="Synthetic caller",
        expected=expected,
    )
    socket = FakeTtsSocket()

    async def connect(*args):
        return socket

    monkeypatch.setattr(run_audio, "get_settings", lambda: settings)
    monkeypatch.setattr(run_audio, "load_personas", lambda **kwargs: [persona])
    monkeypatch.setattr(run_audio, "session_scope", lambda: session_scope(url))
    monkeypatch.setattr("arcagent.speech.cartesia_tts._default_connect", connect)

    def scripted_results(*cases):
        pending = iter(cases)

        async def scenario(**kwargs):
            case = next(pending)
            return run_audio.AudioScenarioResult(
                scenario_id=persona.id,
                group="hot_buyers",
                repeat_index=kwargs["repeat_index"],
                call_sid="CAqualityfixture",
                turns=3,
                barge_ins=0,
                outcome="callback_booked" if case == "wrong_outcome" else "handoff",
                latency_p50_ms=None,
                latency_p95_ms=None,
                error="Synthetic transport error" if case == "error" else None,
                expected=None if case == "missing_expectations" else expected,
                actual_fields=None if case == "missing_snapshot" else {"name": "Pat"},
            )

        monkeypatch.setattr(run_audio, "run_audio_scenario", scenario)

    yield url, scripted_results
    engine.dispose()


@pytest.mark.parametrize(
    ("case", "status"),
    [
        ("success", 0),
        ("wrong_outcome", 1),
        ("error", 1),
        ("missing_snapshot", 1),
        ("missing_expectations", 1),
    ],
)
def test_no_db_cli_exit_status_enforces_quality(quality_cli, monkeypatch, case, status):
    url, scripted_results = quality_cli
    scripted_results(case)
    monkeypatch.setattr(sys, "argv", ["audio-eval", "--run-name", "quality-gate", "--no-db"])
    with pytest.raises(SystemExit) as exited:
        run_audio.main()
    assert exited.value.code == status
    with session_scope(url) as db:
        assert db.scalar(select(func.count()).select_from(EvalRun)) == 0


@pytest.mark.parametrize(("case", "status"), [("success", 0), ("wrong_outcome", 1)])
async def test_database_run_returns_status_not_database_identifier(
    quality_cli, capsys, case, status
):
    url, scripted_results = quality_cli
    with session_scope(url) as db:
        db.add(
            EvalRun(
                id=40,
                run_name="previous-run",
                git_sha="fixture",
                prompt_version="v1",
                threshold=60,
                tier=Tier.AUDIO,
            )
        )
    scripted_results(case)
    exit_status = await run_audio.run(
        Namespace(
            run_name="quality-gate",
            stream_url=run_audio.DEFAULT_STREAM_URL,
            n=1,
            groups=["hot_buyers"],
            ids=None,
            prompts="v1",
            threshold=60,
            caller_voice="fixture-caller-voice",
            no_db=False,
        )
    )
    assert exit_status == status
    assert "run id 41" in capsys.readouterr().out
    with session_scope(url) as db:
        result = db.scalar(select(EvalResult).where(EvalResult.run_id == 41))
        assert result is not None
        assert result.passed is (status == 0)
        assert result.expected["outcome"] == "handoff"
        assert result.actual["outcome"] == ("handoff" if status == 0 else "callback_booked")
        if status:
            assert "outcome_mismatch" in result.notes


def test_one_failed_repeat_makes_the_entire_cli_run_fail(quality_cli, monkeypatch):
    _, scripted_results = quality_cli
    scripted_results("success", "wrong_outcome", "success")
    monkeypatch.setattr(
        sys, "argv", ["audio-eval", "--run-name", "mixed-quality", "--n", "3", "--no-db"]
    )
    with pytest.raises(SystemExit) as exited:
        run_audio.main()
    assert exited.value.code == 1
