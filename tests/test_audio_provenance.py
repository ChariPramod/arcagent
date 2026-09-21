"""Audio provenance handshakes and persisted run labels fail closed."""

import asyncio
import json
from argparse import Namespace

import pytest
from sqlalchemy import select

from arcagent.config import Settings
from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import Base, EvalResult, EvalRun
from evals import run_audio
from evals.fake_twilio import FakeTwilioCall
from evals.persona import Expected, Persona


@pytest.fixture
def peer(monkeypatch):
    class Socket:
        def __init__(self):
            self.incoming = asyncio.Queue()
            self.sent = []

        async def send(self, raw):
            self.sent.append(json.loads(raw))

        async def close(self):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            return json.dumps(await self.incoming.get())

    socket = Socket()

    async def connect(*args, **kwargs):
        return socket

    monkeypatch.setattr("websockets.connect", connect)
    return socket


async def test_missing_config_is_rejected_before_start(peer):
    persona = Persona(
        id="config",
        group="hot_buyers",
        description="fixture",
        background="fixture",
        expected=Expected(outcome="handoff"),
    )
    result = await run_audio.run_audio_scenario(
        persona,
        "ws://localhost/eval/voice/stream",
        None,
        None,
        "voice",
        auth_token="fixture",
        persistence_wait_s=0.01,
        agent_wait_s=0.01,
    )
    assert result.error == "Audio evaluation failed during server configuration (TimeoutError)"
    assert not any(message["event"] == "start" for message in peer.sent)
    assert not result.passed


def server_config(**overrides):
    from arcagent.telephony.eval_config import build_eval_config

    return build_eval_config(Settings(_env_file=None, **overrides), True)


@pytest.mark.parametrize("config", [None, {}, {"schema_version": 2}])
async def test_malformed_config_is_rejected(peer, config):
    peer.incoming.put_nowait({"event": "eval.config", "config": config})
    async with FakeTwilioCall("ws://localhost/eval/voice/stream", auth_token="fixture") as call:
        with pytest.raises(ValueError):
            await call.wait_for_config(wait_s=0.1)


async def test_effective_config_is_returned(peer):
    config = server_config()
    peer.incoming.put_nowait({"event": "eval.config", "config": config})
    async with FakeTwilioCall("ws://localhost/eval/voice/stream", auth_token="fixture") as call:
        assert await call.wait_for_config(wait_s=0.1) == config


@pytest.mark.parametrize(
    "requested", [{"requested_prompt_version": "different"}, {"requested_threshold": 999}]
)
async def test_requested_configuration_is_an_assertion_not_a_label(peer, requested):
    config = server_config()
    peer.incoming.put_nowait({"event": "eval.config", "config": config})
    persona = Persona(
        id="config",
        group="hot_buyers",
        description="fixture",
        background="fixture",
        expected=Expected(outcome="handoff"),
    )
    result = await run_audio.run_audio_scenario(
        persona,
        "ws://localhost/eval/voice/stream",
        None,
        None,
        "voice",
        auth_token="fixture",
        **requested,
    )
    assert result.error == "Audio evaluation failed during server configuration (ValueError)"
    assert result.remote_config == config
    assert not any(message["event"] == "start" for message in peer.sent)


@pytest.fixture
def results_db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'provenance.db'}"
    Base.metadata.create_all(get_engine(url))
    monkeypatch.setattr(run_audio, "session_scope", lambda: session_scope(url))
    return url


def result(config):
    return run_audio.AudioScenarioResult(
        scenario_id="p",
        group="hot_buyers",
        repeat_index=0,
        call_sid="CAfixture",
        turns=1,
        barge_ins=0,
        outcome="handoff",
        latency_p50_ms=None,
        latency_p95_ms=None,
        expected=Expected(outcome="handoff", handoff=True),
        actual_fields={},
        remote_config=config,
    )


def test_persisted_labels_come_from_remote_config_not_client_flags(results_db):
    config = server_config(handoff_threshold=75)
    run_id = run_audio.write_results(
        Namespace(run_name="provenance", prompts="bogus", threshold=999), [result(config)], "sha"
    )
    with session_scope(results_db) as session:
        row = session.get(EvalRun, run_id)
        assert row.prompt_version == "v1"
        assert row.threshold == 75
        record = session.scalar(select(EvalResult).where(EvalResult.run_id == run_id))
        assert record.actual["server_config"] == config
        assert record.passed


def test_mixed_server_config_fails_and_preserves_per_scenario_evidence(results_db):
    first = result(server_config())
    second = result(server_config(handoff_threshold=75))
    run_id = run_audio.write_results(
        Namespace(run_name="mixed", prompts="v1", threshold=60), [first, second], "sha"
    )
    with session_scope(results_db) as session:
        row = session.get(EvalRun, run_id)
        assert (row.prompt_version, row.threshold) == ("mixed", -1)
        records = session.scalars(select(EvalResult).where(EvalResult.run_id == run_id)).all()
        assert not any(record.passed for record in records)
        assert all("server_config_mixed" in record.notes for record in records)
        assert [record.actual["server_config"]["threshold"] for record in records] == [60, 75]


def test_missing_config_never_passes_or_claims_client_labels(results_db):
    missing = result(None)
    assert not missing.passed
    run_id = run_audio.write_results(
        Namespace(run_name="missing", prompts="v1", threshold=60), [missing], "sha"
    )
    with session_scope(results_db) as session:
        row = session.get(EvalRun, run_id)
        assert (row.prompt_version, row.threshold) == ("unverified", -1)
        record = session.scalar(select(EvalResult).where(EvalResult.run_id == run_id))
        assert "server_config_missing" in record.notes


@pytest.mark.parametrize("config", [{}, {"token": "must-not-persist"}])
def test_invalid_config_cannot_pass_or_persist_unvalidated_payload(results_db, config):
    invalid = result(config)
    assert not invalid.passed
    run_id = run_audio.write_results(
        Namespace(run_name="invalid", prompts="v1", threshold=60), [invalid], "sha"
    )
    with session_scope(results_db) as session:
        record = session.scalar(select(EvalResult).where(EvalResult.run_id == run_id))
        assert not record.passed
        assert record.actual["server_config"] is None
        assert "must-not-persist" not in json.dumps(record.actual)
