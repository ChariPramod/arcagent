"""Pure summaries of persisted stage durations, never inferred end-to-end latency."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import ceil
from typing import Any

from arcagent.persistence.models import Speaker, Turn

STAGES = (
    (
        "stt_final_ms",
        "Transcript boundary",
        "Last inbound frame to turn boundary; inbound frames may include silence.",
    ),
    (
        "llm_ttft_ms",
        "Agent first response",
        "Agent invocation to first yielded response; not necessarily provider token TTFT.",
    ),
    (
        "tts_first_byte_ms",
        "Synthesis first byte",
        "Synthesis request to first received audio byte.",
    ),
    (
        "playback_start_ms",
        "Playback acknowledgement",
        "First outgoing frame to playback completion acknowledgement, not audible onset.",
    ),
)
CAVEATS = [
    "Stage durations have different anchors. Do not sum them into response latency.",
    "Caller-perceived speech-end-to-first-audio latency is not measured by these columns.",
    "Missing values include stages that did not run; they are never replaced with zero.",
    "Percentiles use nearest rank. Small samples are descriptive, not performance guarantees.",
]


def _value(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _percentile(values: list[int], quantile: float) -> int | None:
    if not values:
        return None
    return sorted(values)[ceil(len(values) * quantile) - 1]


def _eligible(turn: Turn, key: str) -> bool:
    return key == "stt_final_ms" or turn.speaker == Speaker.AGENT


def latency_report(turns: Sequence[Turn]) -> dict[str, Any]:
    """Analyze loaded turns without querying the database or exposing transcript content."""
    stages = []
    for key, label, description in STAGES:
        eligible = [t for t in turns if _eligible(t, key)]
        raw = [getattr(t, key) for t in eligible]
        samples = [v for item in raw if (v := _value(item)) is not None]
        stages.append(
            {
                "key": key,
                "label": label,
                "description": description,
                "samples": len(samples),
                "eligible_turns": len(eligible),
                "missing": sum(v is None for v in raw),
                "invalid": sum(v is not None and _value(v) is None for v in raw),
                "coverage": len(samples) / len(eligible) if eligible else None,
                "p50_ms": _percentile(samples, 0.5),
                "p95_ms": _percentile(samples, 0.95),
            }
        )
    return {
        "schema_version": 1,
        "measurement": "persisted_stage_durations",
        "turn_count": len(turns),
        "agent_turn_count": sum(t.speaker == Speaker.AGENT for t in turns),
        "caller_perceived_latency_ms": None,
        "caveats": list(CAVEATS),
        "stages": stages,
        "turns": [
            {
                "id": t.id,
                "turn_index": t.turn_index,
                "speaker": str(t.speaker),
                "interrupted": bool(t.interrupted),
                "stages": {key: _value(getattr(t, key)) for key, _, _ in STAGES},
                "invalid_stages": [
                    key
                    for key, _, _ in STAGES
                    if getattr(t, key) is not None and _value(getattr(t, key)) is None
                ],
            }
            for t in sorted(turns, key=lambda t: (t.turn_index, t.id or 0))
        ],
    }


def paired_latency_comparison(
    baseline: Sequence[Turn],
    candidate: Sequence[Turn],
    baseline_provenance: Mapping[str, str],
    candidate_provenance: Mapping[str, str],
) -> dict[str, Any]:
    """Compare matched observations only when their supplied measurement provenance agrees.

    Provenance must be obtained from the experiment runner, not inferred from call IDs.
    Ordinary live calls do not provide this provenance and are not comparable here.
    Deltas are per matched turn before aggregation; unpaired turns never enter the result.
    """
    required = ("scenario_id", "input_digest", "measurement_version", "environment")
    if any(
        not baseline_provenance.get(k) or baseline_provenance.get(k) != candidate_provenance.get(k)
        for k in required
    ):
        return {
            "comparable": False,
            "reason": "Matching measurement provenance is required.",
            "stages": [],
        }
    old = {(t.turn_index, str(t.speaker)): t for t in baseline}
    new = {(t.turn_index, str(t.speaker)): t for t in candidate}
    if len(old) != len(baseline) or len(new) != len(candidate):
        return {"comparable": False, "reason": "Duplicate turn keys prevent pairing.", "stages": []}
    paired = old.keys() & new.keys()
    if not paired:
        return {"comparable": False, "reason": "No matching turns.", "stages": []}
    stages = []
    for key, label, _ in STAGES:
        deltas = []
        for identity in paired:
            a, b = old[identity], new[identity]
            av, bv = _value(getattr(a, key)), _value(getattr(b, key))
            if _eligible(a, key) and av is not None and bv is not None:
                deltas.append(bv - av)
        stages.append(
            {
                "key": key,
                "label": label,
                "paired_samples": len(deltas),
                "delta_p50_ms": _percentile(deltas, 0.5),
                "delta_p95_ms": _percentile(deltas, 0.95),
            }
        )
    return {
        "comparable": True,
        "reason": None,
        "matched_turns": len(paired),
        "unmatched_baseline_turns": len(old) - len(paired),
        "unmatched_candidate_turns": len(new) - len(paired),
        "stages": stages,
    }
