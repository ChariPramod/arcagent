"""Tier 2: the audio level harness.

    python -m evals.run_audio --run-name audio-baseline --groups hot_buyers --n 1

Synthesises each persona utterance with Cartesia in a different voice, pushes mulaw frames
through a fake Twilio WebSocket into the real ``/voice/stream`` handler, and answers when
the agent's mark arrives.

This is what tier 1 cannot see: STT errors, endpointing that cuts a caller off, and barge
in. It is slower and it costs money, so it runs on a subset by default.

Requires a running server (``uvicorn arcagent.app:app``) and real vendor keys.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field

from sqlalchemy import select

from arcagent.agent.llm import AnthropicStructuredLLM
from arcagent.config import get_settings
from arcagent.logging import configure_logging, get_logger
from arcagent.persistence.db import session_scope
from arcagent.persistence.models import Call, Tier, Turn
from arcagent.persistence.repo import EvalRepository
from arcagent.speech.cartesia_tts import CartesiaTTS
from evals import metrics
from evals.fake_twilio import FakeTwilioCall
from evals.persona import Persona, PersonaError, load_personas
from evals.runner import git_sha
from evals.simulator import SimulatedCaller

log = get_logger(__name__)

DEFAULT_STREAM_URL = "ws://localhost:8000/voice/stream"
# The caller must not sound like the agent, or a listener cannot tell who is talking in a
# recording, and neither can the person reviewing a failure.
CALLER_VOICE_ENV = "EVAL_CALLER_VOICE_ID"


@dataclass
class AudioScenarioResult:
    scenario_id: str
    group: str
    repeat_index: int
    call_sid: str
    turns: int
    barge_ins: int
    outcome: str | None
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    stage_latencies: dict[str, list[int]] = field(default_factory=dict)
    error: str | None = None


async def synthesize(tts: CartesiaTTS, text: str, voice_id: str) -> bytes:
    """One caller utterance as raw mulaw, in the caller's voice."""
    audio = bytearray()
    async for chunk in tts.synthesize(text):
        audio.extend(chunk.audio)
    return bytes(audio)


async def run_audio_scenario(
    persona: Persona,
    stream_url: str,
    caller_tts: CartesiaTTS,
    caller_llm: AnthropicStructuredLLM,
    caller_voice_id: str,
    repeat_index: int = 0,
    max_turns: int = 12,
) -> AudioScenarioResult:
    """Play one persona down a real WebSocket and read the latency back from the database."""
    caller = SimulatedCaller(persona=persona, llm=caller_llm)
    error: str | None = None

    async with FakeTwilioCall(stream_url, from_number="+15550000001") as call:
        await call.start()
        try:
            for _ in range(max_turns):
                agent_audio = await call.wait_for_agent()
                if not agent_audio.frames:
                    break
                agent_text = await latest_agent_text(call.call_sid)
                turn = await caller.reply_to([agent_text] if agent_text else [])
                if turn.hung_up or not turn.utterance.strip():
                    break
                spoken = await synthesize(caller_tts, turn.utterance, caller_voice_id)
                await call.play(spoken)
                await call.play_silence(0.4)  # let the endpointer close the turn
        except Exception as exc:  # a live harness must report, not abort the whole run
            error = f"{type(exc).__name__}: {exc}"
            log.warning("audio_scenario_failed", scenario_id=persona.id, error=error)

    stages, outcome = await asyncio.to_thread(read_call_metrics, call.call_sid)
    response_times = stages.get("playback_start_ms", [])
    return AudioScenarioResult(
        scenario_id=persona.id,
        group=str(persona.group),
        repeat_index=repeat_index,
        call_sid=call.call_sid,
        turns=caller.turns_taken,
        barge_ins=call.cleared,
        outcome=outcome,
        latency_p50_ms=int(metrics.percentile(response_times, 50)) if response_times else None,
        latency_p95_ms=int(metrics.percentile(response_times, 95)) if response_times else None,
        stage_latencies=stages,
        error=error,
    )


async def latest_agent_text(call_sid: str) -> str:
    """What the agent last said, read from the turns table.

    The fake Twilio cannot understand speech, so the transcript comes from our own
    database rather than from a second speech to text pass. That is a real limitation of
    tier 2 and it is stated in the README: this tier measures the audio path and the
    latency, not the agent's comprehension of its own output.
    """

    def read() -> str:
        with session_scope() as session:
            call = session.scalar(select(Call).where(Call.twilio_call_sid == call_sid))
            if call is None:
                return ""
            turn = session.scalar(
                select(Turn)
                .where(Turn.call_id == call.id, Turn.speaker == "agent")
                .order_by(Turn.turn_index.desc())
                .limit(1)
            )
            return turn.text if turn else ""

    return await asyncio.to_thread(read)


def read_call_metrics(call_sid: str) -> tuple[dict[str, list[int]], str | None]:
    """Per stage latencies and the outcome, straight from the turns the server wrote."""
    stages: dict[str, list[int]] = {
        "stt_final_ms": [],
        "llm_ttft_ms": [],
        "tts_first_byte_ms": [],
        "playback_start_ms": [],
    }
    with session_scope() as session:
        call = session.scalar(select(Call).where(Call.twilio_call_sid == call_sid))
        if call is None:
            return stages, None
        for turn in session.scalars(select(Turn).where(Turn.call_id == call.id)):
            for stage in stages:
                value = getattr(turn, stage)
                if value is not None:
                    stages[stage].append(value)
        return stages, str(call.outcome) if call.outcome else None


def format_latency(results: list[AudioScenarioResult]) -> str:
    """The latency table. Measured, never estimated."""
    combined: dict[str, list[int]] = {}
    for result in results:
        for stage, values in result.stage_latencies.items():
            combined.setdefault(stage, []).extend(values)

    lines = [
        "",
        "latency by stage, milliseconds",
        "",
        f"{'stage':<20} {'n':>5} {'p50':>7} {'p95':>7}",
    ]
    for stage, values in combined.items():
        if not values:
            lines.append(f"{stage:<20} {0:>5} {'-':>7} {'-':>7}")
            continue
        lines.append(
            f"{stage:<20} {len(values):>5} "
            f"{metrics.percentile(values, 50):>7.0f} {metrics.percentile(values, 95):>7.0f}"
        )
    barge_ins = sum(r.barge_ins for r in results)
    lines += ["", f"barge ins observed: {barge_ins}", f"calls: {len(results)}"]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the audio level eval harness.")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--stream-url", default=DEFAULT_STREAM_URL)
    parser.add_argument("--groups", nargs="*", default=["hot_buyers"])
    parser.add_argument("--ids", nargs="*", default=None)
    parser.add_argument("--n", type=int, default=1, help="repeats per persona")
    parser.add_argument("--prompts", default=settings.prompt_version)
    parser.add_argument("--threshold", type=int, default=settings.handoff_threshold)
    parser.add_argument("--caller-voice", default=None, help="Cartesia voice id for the caller")
    parser.add_argument("--no-db", action="store_true")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    for name, value in (
        ("CARTESIA_API_KEY", settings.cartesia_api_key),
        ("LLM_API_KEY", settings.llm_api_key),
    ):
        if not value:
            raise SystemExit(f"{name} is not set. Tier 2 needs real vendor keys.")

    caller_voice = args.caller_voice or settings.cartesia_voice_id
    if caller_voice == settings.cartesia_voice_id:
        print(
            "warning: the caller and the agent are using the same voice. Pass "
            "--caller-voice so a recording is intelligible."
        )

    try:
        personas = load_personas(groups=args.groups, ids=args.ids)
    except PersonaError as exc:
        raise SystemExit(f"persona error: {exc}") from exc
    if not personas:
        raise SystemExit("no personas matched. evals/personas/ is owner authored.")

    caller_llm = AnthropicStructuredLLM(settings)
    results: list[AudioScenarioResult] = []

    async with CartesiaTTS(settings) as caller_tts:
        for repeat in range(args.n):
            for persona in personas:
                print(f"  {persona.id} r{repeat} ...", flush=True)
                result = await run_audio_scenario(
                    persona=persona,
                    stream_url=args.stream_url,
                    caller_tts=caller_tts,
                    caller_llm=caller_llm,
                    caller_voice_id=caller_voice,
                    repeat_index=repeat,
                )
                results.append(result)
                print(
                    f"    outcome={result.outcome}  turns={result.turns}  "
                    f"barge_ins={result.barge_ins}  p50={result.latency_p50_ms}ms"
                    + (f"  error={result.error}" if result.error else "")
                )

    print(format_latency(results))
    if args.no_db:
        return 0
    return write_results(args, results, git_sha())


def write_results(args: argparse.Namespace, results: list[AudioScenarioResult], sha: str) -> int:
    with session_scope() as session:
        repo = EvalRepository(session)
        run_row = repo.create_run(
            run_name=args.run_name,
            git_sha=sha,
            prompt_version=args.prompts,
            threshold=args.threshold,
            tier=Tier.AUDIO,
        )
        for result in results:
            repo.add_result(
                run_row.id,
                scenario_id=result.scenario_id,
                repeat_index=result.repeat_index,
                passed=result.error is None,
                latency_p50_ms=result.latency_p50_ms,
                latency_p95_ms=result.latency_p95_ms,
                actual={"outcome": result.outcome, "barge_ins": result.barge_ins},
                notes=result.error,
            )
        return run_row.id


def main() -> None:
    configure_logging(level="WARNING")
    run_id = asyncio.run(run(parse_args()))
    if run_id:
        print(f"\nrun id {run_id}")


if __name__ == "__main__":
    main()
