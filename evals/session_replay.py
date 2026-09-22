"""Offline fixture replay against the real session; dependency adapters are scripted.

No network, database, prompts, LLM or global patching. Fixed event phases rather than
wall-clock delays define the fixture. The wall-clock watchdog only bounds a broken run.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arcagent.config import Settings
from arcagent.speech.deepgram_stt import TranscriptEvent
from arcagent.telephony.call_session import CallSession
from arcagent.telephony.session_handler import SocketClosed

_SCENARIOS = ("interrupt", "disconnect", "vendor_failure")


class _Media:
    def __init__(self):
        self.incoming: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []
        self.changed = asyncio.Event()

    async def receive_json(self):
        message = await self.incoming.get()
        if message is None:
            raise SocketClosed
        return message

    async def send_json(self, message):
        self.sent.append(message)
        self.changed.set()

    async def wait_for(self, kind):
        while not any(message["event"] == kind for message in self.sent):
            self.changed.clear()
            await self.changed.wait()


class _Transcripts:
    def __init__(self):
        self.events: asyncio.Queue = asyncio.Queue()
        self.processed = asyncio.Event()

    async def send_audio(self, _audio):
        pass

    async def __aiter__(self):
        while True:
            event = await self.events.get()
            yield event
            self.processed.set()


@dataclass(frozen=True)
class _Chunk:
    audio: bytes
    ts: float = 0.0


class _Speech:
    def __init__(self, fail: bool):
        self.fail = fail
        self.cancelled: list[str] = []
        self.release = asyncio.Event()
        self.contexts = 0

    def new_context_id(self):
        self.contexts += 1
        return f"fixture-{self.contexts}"

    async def synthesize(self, _text, context_id):
        if self.fail:
            raise RuntimeError("scripted synthesis failure")
        yield _Chunk(b"\xff" * 160)
        # Keep synthesis in progress until production cancellation stops it.
        await self.release.wait()
        yield _Chunk(b"\xff" * 160)

    async def cancel(self, context_id):
        self.cancelled.append(context_id)


class _Responder:
    node_name = "scripted_fixture"
    should_end = False

    async def respond(self, _transcript):
        yield "Fictional scripted greeting."


def _validate(payload, allowed):
    if not isinstance(payload, dict) or payload.keys() - allowed:
        raise ValueError("Invalid session replay request")
    if type(payload.get("version")) is not int or payload["version"] != 1:
        raise ValueError("Session replay requires version 1")
    if payload.get("scenario_id") not in _SCENARIOS:
        raise ValueError("Unknown session replay scenario")


def _config(config):
    if not isinstance(config, dict) or config.keys() - {"barge_in_min_words"}:
        raise ValueError("Invalid session replay configuration")
    value = config.get("barge_in_min_words", 2)
    if type(value) is not int or not 1 <= value <= 10:
        raise ValueError("barge_in_min_words must be an integer from 1 to 10")
    return {"barge_in_min_words": value}


async def replay_session(payload: Any) -> dict[str, Any]:
    """Run a fixed versioned fixture. Exceptions/timeouts propagate, never report success."""
    _validate(payload, {"version", "scenario_id", "config"})
    config = _config(payload.get("config", {}))
    scenario = payload["scenario_id"]
    socket, stt, tts = _Media(), _Transcripts(), _Speech(scenario == "vendor_failure")
    # Construct deterministic safe settings without consulting environment credentials.
    settings = Settings.model_construct(barge_in_min_words=config["barge_in_min_words"])
    session = CallSession(socket, stt, tts, _Responder(), settings, clock=lambda: 0.0)
    socket.incoming.put_nowait(
        {
            "event": "start",
            "streamSid": "MZ_fixture",
            "start": {
                "streamSid": "MZ_fixture",
                "callSid": "CA_fixture",
                "accountSid": "AC_fixture",
                "tracks": ["inbound"],
                "customParameters": {},
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
            },
        }
    )
    task = asyncio.create_task(session.run(), name="offline-session-replay")
    fixture_events = ["stream_start", "scripted_greeting"]
    try:
        async with asyncio.timeout(3):
            if scenario == "vendor_failure":
                fixture_events.append("synthesis_exception")
                await task
            else:
                await socket.wait_for("media")
                if scenario == "interrupt":
                    fixture_events.append("interim_transcript_three_words")
                    stt.events.put_nowait(
                        TranscriptEvent("please stop speaking", False, False, 0.0)
                    )
                    await stt.processed.wait()
                fixture_events.append("caller_disconnect")
                socket.incoming.put_nowait(None)
                await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    observed = {
        "barge_ins": session.barge_ins,
        "clear_count": sum(message["event"] == "clear" for message in socket.sent),
        "media_frames": sum(message["event"] == "media" for message in socket.sent),
        "tts_cancellations": len(tts.cancelled),
        "outcome": session.outcome,
        "state": session.state.value,
        "interrupted_agent_turns": sum(
            turn.speaker == "agent" and turn.interrupted for turn in session.turns
        ),
    }
    checks = {
        "session_ended": observed["state"] == "ending",
        "truthful_abandonment": observed["outcome"] == "abandoned",
    }
    if scenario == "interrupt":
        checks.update(
            {
                "interruption_observed": observed["barge_ins"] == 1,
                "playback_cleared": observed["clear_count"] == 1,
                "synthesis_cancelled": observed["tts_cancellations"] == 1,
            }
        )
    elif scenario == "vendor_failure":
        checks.update(
            {
                "failed_output_cleared": observed["clear_count"] == 1,
                "no_audio_sent": observed["media_frames"] == 0,
            }
        )
    else:
        checks["partial_output_not_completed"] = observed["interrupted_agent_turns"] == 1
    return {
        "version": 1,
        "scenario_id": scenario,
        "config": config,
        "implementation": "arcagent.telephony.call_session.CallSession",
        "implementation_sha256": hashlib.sha256(
            await asyncio.to_thread(Path(inspect.getfile(CallSession)).read_bytes)
        ).hexdigest(),
        "provenance": "synthetic fixture v1; real session; scripted media/STT/TTS/responder",
        "timing": "synthetic clock; latency not measured",
        "simulated_dependencies": True,
        "fixture_events": fixture_events,
        "observed": observed,
        "assertions": [{"name": name, "passed": passed} for name, passed in checks.items()],
        "passed": all(checks.values()),
    }


async def compare_sessions(payload: Any) -> dict[str, Any]:
    _validate(payload, {"version", "scenario_id", "baseline_config", "candidate_config"})
    baseline_config = _config(payload.get("baseline_config", {}))
    candidate_config = _config(payload.get("candidate_config", {}))
    common = {"version": 1, "scenario_id": payload["scenario_id"]}
    baseline = await replay_session(common | {"config": baseline_config})
    candidate = await replay_session(common | {"config": candidate_config})
    return {
        "baseline": baseline,
        "candidate": candidate,
        "changes": [
            {"field": key, "before": baseline[key], "after": candidate[key]}
            for key in ("config", "observed", "assertions", "passed")
            if baseline[key] != candidate[key]
        ],
    }
