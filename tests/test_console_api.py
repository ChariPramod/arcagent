"""The console exposes saved records only after server-to-server authentication."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arcagent.config import Settings, get_settings
from arcagent.console.api import database, router
from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import (
    Base,
    Call,
    Decision,
    Lead,
    LeadScore,
    Outcome,
    Speaker,
    Tier,
    Turn,
)
from arcagent.persistence.repo import EvalRepository
from tests.test_eval_snapshots import snapshot_payload


@pytest.fixture
def console(tmp_path):
    url = f"sqlite:///{tmp_path / 'console.db'}"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, console_api_token="fixture-token"
    )

    def db():
        with session_scope(url) as session:
            yield session

    app.dependency_overrides[database] = db
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer fixture-token"
        yield client, url, app
    engine.dispose()


def test_authentication_precedes_database_access(console):
    client, _, app = console

    def forbidden():
        pytest.fail("Unauthenticated request opened the database")

    app.dependency_overrides[database] = forbidden
    for header in ["", "Bearer incorrect", "Basic fixture-token"]:
        assert (
            client.get("/api/console/calls", headers={"Authorization": header}).status_code == 401
        )
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, console_api_token="")
    assert client.get("/api/console/calls").status_code == 503


def test_saved_score_and_transcript_are_returned_without_recomputation(console):
    client, url, _ = console
    with session_scope(url) as session:
        call = Call(twilio_call_sid="fixture", from_number_hash="redacted", outcome=Outcome.HANDOFF)
        call.lead = Lead(
            name="Synthetic caller",
            scores=[
                LeadScore(
                    score=7,
                    threshold_used=5,
                    decision=Decision.HANDOFF,
                    score_breakdown={"historical_rule": 7},
                )
            ],
        )
        call.turns = [
            Turn(turn_index=1, speaker=Speaker.AGENT, text="Second", playback_start_ms=200),
            Turn(turn_index=0, speaker=Speaker.CALLER, text="First"),
        ]
        session.add(call)
        session.flush()
        call_id = call.id
    response = client.get(f"/api/console/calls/{call_id}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["score"] == 7
    assert data["threshold"] == 5
    assert data["score_breakdown"] == {"historical_rule": 7}
    assert [t["text"] for t in data["turns"]] == ["First", "Second"]
    assert data["turns"][0]["latency"]["tts_first_byte_ms"] is None
    assert data["turns"][1]["latency"]["playback_start_ms"] == 200
    assert "twilio_call_sid" not in data
    assert "from_number_hash" not in data


def test_pagination_filters_and_absent_lead(console):
    client, url, _ = console
    with session_scope(url) as session:
        session.add_all(
            [
                Call(
                    twilio_call_sid=str(i),
                    from_number_hash="fixture",
                    outcome=Outcome.WRONG_NUMBER if i == 0 else Outcome.HANDOFF,
                )
                for i in range(3)
            ]
        )
    data = client.get("/api/console/calls?limit=1&offset=1").json()
    assert data["total"] == 3
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] is None
    assert data["items"][0]["score"] is None
    assert client.get("/api/console/calls?outcome=wrong_number").json()["total"] == 1
    for query in ["limit=101", "offset=-1", "outcome=invalid"]:
        assert client.get(f"/api/console/calls?{query}").status_code == 422
    for route in ["calls/999", "evals/999", "compare?before=998&after=999"]:
        assert client.get(f"/api/console/{route}").status_code == 404


def test_evaluation_snapshots_transcripts_and_regression_guards(console):
    client, url, _ = console
    snapshot = snapshot_payload()
    ids = []
    with session_scope(url) as session:
        repo = EvalRepository(session)
        for name, hot_pass in [("before", True), ("after", False)]:
            run = repo.create_run(name, "fixture-sha", "v1", 60, Tier.TEXT, snapshot=snapshot)
            ids.append(run.id)
            for scenario_id, persona in snapshot["personas"].items():
                hot = scenario_id == "fixture_hot"
                repo.add_result(
                    run.id,
                    scenario_id=scenario_id,
                    expected=persona["expected"]["fields"],
                    actual={},
                    transcript=[{"speaker": "agent", "text": "Saved example"}],
                    passed=hot_pass if hot else True,
                    field_accuracy=1.0,
                    handoff_expected=hot,
                    handoff_actual=hot and hot_pass,
                    crm_completeness=1.0,
                )
        empty = repo.create_run("empty", "fixture-sha", "v1", 60, Tier.TEXT)
        empty_id = empty.id
    detail = client.get(f"/api/console/evals/{ids[0]}").json()
    assert detail["pass_rate"] == 1.0
    assert detail["items"][0]["group"] == "hot_buyers"
    assert detail["items"][0]["transcript"] == [{"speaker": "agent", "text": "Saved example"}]
    empty_data = client.get(f"/api/console/evals/{empty_id}").json()
    assert empty_data["pass_rate"] is None
    assert empty_data["handoff_recall"] is None
    comparison = client.get(f"/api/console/compare?before={ids[0]}&after={ids[1]}").json()
    assert comparison["status"] == "regression"
    assert any(
        row["group"] == "hot_buyers" and row["name"] == "handoff_recall"
        for row in comparison["regressions"]
    )
    assert (
        client.get(f"/api/console/compare?before={ids[0]}&after={empty_id}").json()["status"]
        == "invalid"
    )
    assert client.get("/api/console/evals?limit=1").json()["total"] == 3
