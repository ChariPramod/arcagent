"""Pure audio evaluation quality assessment using the shared persona metrics."""

from dataclasses import dataclass
from typing import Any

from evals import metrics
from evals.persona import Expected


@dataclass(frozen=True, slots=True)
class AudioAssessment:
    passed: bool
    outcome_correct: bool
    handoff_correct: bool
    field_accuracy: float | None
    missed_fields: tuple[str, ...]
    reasons: tuple[str, ...]


def assess_audio(
    expected: Expected,
    actual_fields: dict[str, Any] | None,
    outcome: str | None,
    error: str | None,
    turns: int,
) -> AudioAssessment:
    """Compare an audio result to expectations without retaining caller text or errors."""
    fields = metrics.field_accuracy(expected.fields, actual_fields or {}, expected.not_expected)
    outcome_ok = metrics.outcome_correct(expected.outcome, outcome)
    handoff_ok = expected.handoff == (outcome == "handoff")
    reasons: list[str] = []
    if error is not None:
        reasons.append("transport_error")
    if turns <= 0:
        reasons.append("no_caller_turns")
    if actual_fields is None:
        reasons.append("missing_snapshot")
    if not outcome_ok:
        reasons.append("outcome_mismatch")
    if not handoff_ok:
        reasons.append("handoff_mismatch")
    if fields.missed:
        reasons.append("field_mismatch")
    return AudioAssessment(
        not reasons,
        outcome_ok,
        handoff_ok,
        fields.accuracy if actual_fields is not None else None,
        fields.missed,
        tuple(reasons),
    )
