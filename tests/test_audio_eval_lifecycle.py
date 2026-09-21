"""Audio evaluation lifecycle against persisted turns and the WebSocket boundary."""

import asyncio

import pytest

from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import Base, Outcome
from arcagent.persistence.repo import CallRepository
from evals import run_audio


@pytest.fixture
def audio_db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'audio-lifecycle.db'}"
    Base.metadata.create_all(get_engine(url))
    monkeypatch.setattr(run_audio, "session_scope", lambda: session_scope(url))
    with session_scope(url) as session:
        repo = CallRepository(session)
        call_id = repo.start_call("CA-lifecycle", "+15550000001").id
        repo.add_turn(call_id, 0, "agent", "Previous question")
    return url, call_id


async def test_acknowledged_turn_waits_for_new_committed_text(audio_db):
    url, call_id = audio_db

    async def commit_new_turn():
        await asyncio.sleep(0.02)
        with session_scope(url) as session:
            CallRepository(session).add_turn(call_id, 2, "agent", "Fresh question")

    writer = asyncio.create_task(commit_new_turn())
    try:
        index, text = await run_audio.wait_for_agent_turn("CA-lifecycle", after_index=0, wait_s=1)
    finally:
        await writer
    assert (index, text) == (2, "Fresh question")


async def test_missing_new_turn_times_out_instead_of_reusing_old_text(audio_db):
    with pytest.raises(TimeoutError):
        await run_audio.wait_for_agent_turn("CA-lifecycle", after_index=0, wait_s=0.03)


async def test_final_metrics_wait_for_call_close_commit(audio_db):
    url, call_id = audio_db

    async def finish_later():
        await asyncio.sleep(0.02)
        with session_scope(url) as session:
            CallRepository(session).end_call(call_id, Outcome.NOT_A_LEAD)

    writer = asyncio.create_task(finish_later())
    try:
        _, outcome = await run_audio.wait_for_call_metrics("CA-lifecycle", wait_s=1)
    finally:
        await writer
    assert outcome == "not_a_lead"


async def test_unfinalized_call_times_out(audio_db):
    with pytest.raises(TimeoutError):
        await run_audio.wait_for_call_metrics("CA-lifecycle", wait_s=0.03)


def persona():
    from evals.persona import Expected, Persona, PersonaGroup

    return Persona(
        id="lifecycle",
        group=PersonaGroup.HOT_BUYERS,
        description="Lifecycle fixture",
        background="Synthetic caller",
        expected=Expected(outcome="not_a_lead"),
    )


async def test_handshake_failure_becomes_a_sanitized_scenario_result(monkeypatch):
    async def fail_connect(*args, **kwargs):
        raise RuntimeError("secret-token and sensitive caller text")

    monkeypatch.setattr("websockets.connect", fail_connect)
    result = await run_audio.run_audio_scenario(
        persona(),
        "ws://localhost/eval/voice/stream",
        None,
        None,
        "voice",
        auth_token="secret-token",
    )
    assert result.error == "Audio evaluation failed during connection (RuntimeError)"
    assert result.outcome is None
    assert result.turns == 0


@pytest.mark.parametrize("payloads", [[], [b"\xff" * 160]])
async def test_absent_or_unmarked_agent_audio_fails(monkeypatch, payloads):
    import base64
    import json

    class Socket:
        def __init__(self):
            self.messages = asyncio.Queue()
            for audio in payloads:
                self.messages.put_nowait(
                    json.dumps(
                        {"event": "media", "media": {"payload": base64.b64encode(audio).decode()}}
                    )
                )

        async def send(self, raw):
            pass

        async def close(self):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            return await self.messages.get()

    async def connect(*args, **kwargs):
        return Socket()

    monkeypatch.setattr("websockets.connect", connect)
    result = await run_audio.run_audio_scenario(
        persona(),
        "ws://localhost/eval/voice/stream",
        None,
        None,
        "voice",
        auth_token="fixture",
        agent_wait_s=0.01,
    )
    assert result.error == "Audio evaluation failed during agent audio playback (TimeoutError)"
    assert result.turns == 0


@pytest.mark.parametrize("fail_database", [False, True])
async def test_scenario_waits_for_ack_and_finalization_commits(
    audio_db, monkeypatch, fail_database
):
    import base64
    import json
    from types import SimpleNamespace

    from evals.simulator import CallerTurn

    url, _ = audio_db
    writers = []
    heard = []

    class Socket:
        def __init__(self):
            self.messages = asyncio.Queue()
            self.call_id = None

        async def send(self, raw):
            message = json.loads(raw)
            if message["event"] == "start":
                with session_scope(url) as session:
                    self.call_id = (
                        CallRepository(session)
                        .start_call(message["start"]["callSid"], "+15550000001")
                        .id
                    )
                self.messages.put_nowait(
                    json.dumps(
                        {
                            "event": "media",
                            "media": {"payload": base64.b64encode(b"\xff" * 160).decode()},
                        }
                    )
                )
                self.messages.put_nowait(
                    json.dumps({"event": "mark", "mark": {"name": "greeting"}})
                )
            elif message["event"] == "mark":
                if fail_database:
                    with session_scope(url) as session:
                        Base.metadata.drop_all(session.get_bind())
                    self.complete_reply()
                else:
                    writers.append(asyncio.create_task(self.persist_later(False)))
            elif message["event"] == "stop" and not fail_database:
                writers.append(asyncio.create_task(self.persist_later(True)))

        def complete_reply(self):
            self.messages.put_nowait(
                json.dumps(
                    {
                        "event": "eval.reply_complete",
                        "reply": {"texts": ["Goodbye"], "terminal": False},
                    }
                )
            )

        async def persist_later(self, finish):
            await asyncio.sleep(0.02)
            with session_scope(url) as session:
                repo = CallRepository(session)
                if finish:
                    repo.end_call(self.call_id, Outcome.NOT_A_LEAD)
                else:
                    repo.add_turn(
                        self.call_id, 0, "agent", "Goodbye", latency={"playback_start_ms": 40}
                    )
            if not finish:
                self.complete_reply()

        async def close(self):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            return await self.messages.get()

    class CallerModel:
        async def complete(self, **kwargs):
            heard.extend(message["content"] for message in kwargs["messages"])
            return SimpleNamespace(parsed=CallerTurn(utterance="", hung_up=True))

    async def connect(*args, **kwargs):
        return Socket()

    monkeypatch.setattr("websockets.connect", connect)
    try:
        result = await run_audio.run_audio_scenario(
            persona(),
            "ws://localhost/eval/voice/stream",
            None,
            CallerModel(),
            "voice",
            auth_token="fixture",
            persistence_wait_s=1,
        )
    finally:
        await asyncio.gather(*writers)
    if fail_database:
        assert (
            result.error
            == "Audio evaluation failed during agent transcript persistence (OperationalError)"
        )
        assert heard == []
    else:
        assert result.error is None
        assert heard == ["Goodbye"]
        assert result.outcome == "not_a_lead"
        assert result.stage_latencies["playback_start_ms"] == [40]
        assert result.latency_p50_ms is None


async def test_fresh_turn_poll_skips_interrupted_unacknowledged_text(audio_db):
    url, call_id = audio_db
    with session_scope(url) as session:
        repo = CallRepository(session)
        repo.add_turn(call_id, 1, "agent", "Cleared words", interrupted=True)
        repo.add_turn(call_id, 2, "agent", "Completed words")
    assert await run_audio.wait_for_agent_turn("CA-lifecycle", after_index=0) == (
        2,
        "Completed words",
    )
