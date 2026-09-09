"""Conversation evidence survives an eval and remains readable after a restart."""

from argparse import Namespace
from pathlib import Path

import pytest

from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import Base
from arcagent.persistence.repo import EvalRepository
from evals.persona import load_persona
from evals.run_text import write_results
from evals.runner import run_scenario
from tests.test_eval_harness import FIXTURES, ScriptedEvalLLM


@pytest.fixture
def eval_database(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'transcripts.db'}"
    Base.metadata.create_all(get_engine(url))
    monkeypatch.setattr("evals.run_text.session_scope", lambda: session_scope(url))
    return url


async def test_transcript_round_trips_for_each_repeat(eval_database) -> None:
    persona = load_persona(FIXTURES / "fixture_hot.yaml")
    results = []
    for repeat in range(2):
        llm = ScriptedEvalLLM(
            agent=[{"next_utterance": "Tell me more.", "treatment_interest": "full_arch"}],
            caller=[
                {"utterance": f"My teeth, attempt {repeat}"},
                {"utterance": "", "hung_up": True},
            ],
        )
        results.append(await run_scenario(persona, llm, llm, repeat_index=repeat))
    args = Namespace(run_name="transcript-test", prompts="v1", threshold=60)
    run_id = write_results(args, results, sha="fixture")

    with session_scope(eval_database) as session:
        rows = sorted(EvalRepository(session).results_for(run_id), key=lambda r: r.repeat_index)
        assert len(rows) == 2
        for row, result in zip(rows, results, strict=True):
            assert row.transcript == [
                {"speaker": speaker, "text": text} for speaker, text in result.transcript
            ]
            assert row.expected == result.expected
            assert row.actual == result.actual
        assert rows[0].transcript != rows[1].transcript


async def test_hangup_does_not_repeat_the_last_agent_line() -> None:
    persona = load_persona(FIXTURES / "fixture_hot.yaml")
    llm = ScriptedEvalLLM(agent=[], caller=[{"utterance": "", "hung_up": True}])
    result = await run_scenario(persona, llm, llm)
    assert len(result.transcript) == 1
    assert result.transcript[0][0] == "agent"


async def test_terminal_agent_response_is_kept_without_another_caller_turn() -> None:
    persona = load_persona(FIXTURES / "fixture_hot.yaml")
    llm = ScriptedEvalLLM(
        agent=[{"next_utterance": "Sorry about that.", "treatment_interest": "wrong_number"}],
        caller=[{"utterance": "I was trying to reach the bakery"}],
    )
    result = await run_scenario(persona, llm, llm)
    assert result.outcome_actual == "wrong_number"
    assert [speaker for speaker, _ in result.transcript] == ["agent", "caller", "agent"]
    assert result.transcript[-1] == ("agent", "Sorry about that.")


def test_dashboard_displays_saved_transcript_and_legacy_results(eval_database, monkeypatch) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    from arcagent.persistence.models import Tier

    transcript = [
        {"speaker": "agent", "text": "How can I help?"},
        {"speaker": "caller", "text": "I am worried about **surgery**. <script>literal</script>"},
    ]
    with session_scope(eval_database) as session:
        repo = EvalRepository(session)
        run = repo.create_run("review", "fixture", "v1", 60, Tier.TEXT)
        repo.add_result(run.id, scenario_id="saved", transcript=transcript)
        repo.add_result(run.id, scenario_id="legacy")
        repo.add_result(run.id, scenario_id="empty", transcript=[])

    monkeypatch.setattr(
        "arcagent.persistence.db.session_scope", lambda: session_scope(eval_database)
    )
    import streamlit as st

    st.cache_data.clear()
    try:
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard/app.py"))
        app.run()
        app.sidebar.radio[0].set_value("Run detail").run()
        assert not app.exception
        app.selectbox[1].set_value("saved").run()
        assert not app.exception
        assert [element.value for element in app.text] == [turn["text"] for turn in transcript]
        assert "Transcript" in [element.value for element in app.caption]
        app.selectbox[1].set_value("legacy").run()
        assert not app.exception
        assert any("No transcript was recorded" in element.value for element in app.info)
        app.selectbox[1].set_value("empty").run()
        assert not app.exception
        assert any("No utterances were captured" in element.value for element in app.info)
    finally:
        st.cache_data.clear()
