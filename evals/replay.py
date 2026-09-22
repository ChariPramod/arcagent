"""Bounded, deterministic policy simulations. These do not replay the audio pipeline.

Only the lead-scoring calculation invokes production behavior. All time and transport
failures are fictional inputs; results cannot establish vendor or audio reliability.
"""

from __future__ import annotations

from typing import Any

from arcagent.agent.scoring import score
from arcagent.agent.state import LeadFields, TreatmentInterest

PROVENANCE = "synthetic-policy-v1; real scoring; simulated transport and timing; no vendor calls"
DEFAULT_CONFIG = {
    "vendor_timeout_ms": 2000,
    "transcript_timeout_ms": 1500,
    "handoff_threshold": 60,
}
_BOUNDS = {
    "vendor_timeout_ms": (100, 30000),
    "transcript_timeout_ms": (100, 10000),
    "handoff_threshold": (0, 100),
}
# Authored expectations remain constant when candidate settings change.
_SCENARIOS = {
    "silence": (
        "Prolonged silence",
        "Two unanswered checks lead to a callback offer.",
        "offer_callback",
        "handoff",
    ),
    "interrupt": (
        "Caller interruption",
        "Playback is cleared and cancelled audio stays cancelled.",
        "clear_playback",
        "resume_cancelled_audio",
    ),
    "delayed_transcript": (
        "Late transcript",
        "An expired turn rejects a transcript arriving after its deadline.",
        "discard_late_transcript",
        "respond_to_late_transcript",
    ),
    "vendor_timeout": (
        "Vendor timeout",
        "A stalled request ends with a callback offer without an automatic retry.",
        "offer_callback",
        "retry_vendor",
    ),
    "disconnect": (
        "Caller disconnect",
        "Pending work is cancelled and later audio is dropped.",
        "cancel_pending_work",
        "send_after_disconnect",
    ),
    "unanswered_handoff": (
        "Unanswered handoff",
        "A qualified lead receives a callback offer after a failed transfer.",
        "attempt_handoff",
        "claim_transfer_success",
    ),
}


def scenario_catalog() -> list[dict[str, str]]:
    """Return fresh metadata without exposing mutable scenario definitions."""
    return [
        {"id": key, "title": value[0], "description": value[1]} for key, value in _SCENARIOS.items()
    ]


def _config(value: Any) -> dict[str, int]:
    if not isinstance(value, dict) or value.keys() - DEFAULT_CONFIG.keys():
        raise ValueError("Unknown or invalid replay configuration")
    result = DEFAULT_CONFIG.copy()
    for key, number in value.items():
        minimum, maximum = _BOUNDS[key]
        if type(number) is not int or not minimum <= number <= maximum:
            raise ValueError(f"{key} must be an integer from {minimum} to {maximum}")
        result[key] = number
    return result


def replay(request: Any) -> dict[str, Any]:
    """Run one fixed synthetic scenario with a strictly bounded configuration."""
    if not isinstance(request, dict) or request.keys() - {"scenario_id", "config"}:
        raise ValueError("Invalid replay request")
    scenario = request.get("scenario_id")
    if not isinstance(scenario, str) or scenario not in _SCENARIOS:
        raise ValueError("Unknown scenario_id")
    config = _config(request.get("config", {}))
    events: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    route = None
    lead_score = None

    def event(at_ms: int, kind: str) -> None:
        events.append({"at_ms": at_ms, "type": kind})

    def act(at_ms: int, kind: str) -> None:
        actions.append({"at_ms": at_ms, "type": kind})

    event(0, "call_started")
    if scenario == "silence":
        for at_ms in (5000, 10000):
            event(at_ms, "silence_deadline")
            act(at_ms, "check_presence")
        event(15000, "silence_deadline")
        act(15000, "offer_callback")
    elif scenario == "interrupt":
        event(100, "playback_started")
        event(400, "caller_speech_started")
        act(400, "cancel_generation")
        act(400, "clear_playback")
        event(450, "cancelled_audio_arrived")
        act(450, "discard_cancelled_audio")
    elif scenario == "delayed_transcript":
        deadline = config["transcript_timeout_ms"]
        event(0, "caller_speech_ended")
        if deadline <= 3000:
            event(deadline, "transcript_deadline")
            act(deadline, "ask_to_repeat")
            event(3000, "transcript_arrived")
            act(3000, "discard_late_transcript")
        else:
            event(3000, "transcript_arrived")
            act(3000, "accept_transcript")
    elif scenario == "vendor_timeout":
        deadline = config["vendor_timeout_ms"]
        event(0, "vendor_request_started")
        event(deadline, "vendor_deadline")
        act(deadline, "cancel_vendor_request")
        act(deadline, "offer_callback")
    elif scenario == "disconnect":
        event(100, "vendor_request_started")
        event(200, "caller_disconnected")
        act(200, "cancel_pending_work")
        event(800, "audio_arrived")
        act(800, "discard_audio")
    else:
        fields = LeadFields(
            treatment_interest=TreatmentInterest.FULL_ARCH, pain_level=7, has_insurance=True
        )
        scored = score(fields, threshold=config["handoff_threshold"])
        lead_score, route = scored.score, scored.decision.value
        event(100, "qualification_complete")
        if scored.is_handoff:
            act(100, "attempt_handoff")
            event(30100, "coordinator_no_answer")
            act(30100, "offer_callback")
        else:
            act(100, "offer_callback")
    required, forbidden = _SCENARIOS[scenario][2:]
    action_types = [action["type"] for action in actions]
    assertions = [
        {
            "name": "expected_action",
            "expected": required,
            "actual": action_types,
            "passed": required in action_types,
        },
        {
            "name": "forbidden_action_absent",
            "expected": forbidden,
            "actual": action_types,
            "passed": forbidden not in action_types,
        },
    ]
    if scenario == "unanswered_handoff":
        assertions.append(
            {
                "name": "callback_fallback",
                "expected": "offer_callback",
                "actual": action_types,
                "passed": "offer_callback" in action_types,
            }
        )
    return {
        "scenario_id": scenario,
        "simulated": True,
        "provenance": PROVENANCE,
        "config": config,
        "events": events,
        "actions": actions,
        "assertions": assertions,
        "metrics": {
            "duration_ms": max(item["at_ms"] for item in events + actions),
            "action_count": len(actions),
            "score": lead_score,
            "route": route,
        },
        "passed": all(assertion["passed"] for assertion in assertions),
    }


def compare_replays(request: Any) -> dict[str, Any]:
    """Compare fixed inputs, never adapt expected behavior to the candidate."""
    if not isinstance(request, dict) or request.keys() - {
        "scenario_id",
        "baseline_config",
        "candidate_config",
    }:
        raise ValueError("Invalid comparison request")
    baseline = replay(
        {"scenario_id": request.get("scenario_id"), "config": request.get("baseline_config", {})}
    )
    candidate = replay(
        {"scenario_id": request.get("scenario_id"), "config": request.get("candidate_config", {})}
    )
    changes = [
        {"field": field, "before": baseline[field], "after": candidate[field]}
        for field in ("config", "events", "actions", "assertions", "metrics", "passed")
        if baseline[field] != candidate[field]
    ]
    return {"simulated": True, "baseline": baseline, "candidate": candidate, "changes": changes}
