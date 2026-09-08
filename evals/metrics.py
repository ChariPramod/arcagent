"""Metric definitions, from scope section 7.2.

Every metric is a pure function over what a run produced and what the persona expected,
with the definition in the docstring. When a number reaches the README it should be
traceable to one of these and to a run id, and nothing else.

Two rules that keep the numbers honest:
  - a field the persona says the caller never mentioned is not an extraction failure. It
    is excluded, not counted wrong.
  - a pass rate is meaningless without its spread, so every aggregate reports variance and
    the count of scenarios that flip between repeats.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


def _normalise(value: Any) -> Any:
    """Compare enums by value, strings case and whitespace insensitively, numbers as numbers."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    if hasattr(value, "value"):
        return _normalise(value.value)
    return value


# US numbers only, per the scope. Twilio hands back E.164 (+14155550123) while a caller
# says ten digits, so the last ten are what actually identify the line.
US_NATIONAL_DIGITS = 10


def _digits(value: Any) -> str:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits[-US_NATIONAL_DIGITS:] if len(digits) > US_NATIONAL_DIGITS else digits


PHONE_FIELDS = frozenset({"callback_number"})


def field_matches(name: str, expected: Any, actual: Any) -> bool:
    """One field comparison.

    Enums and booleans are exact. Phone numbers compare on their last ten digits, because
    a caller reading a number aloud, the persona's version of it, and Twilio's E.164 form
    differ by punctuation and a country code and nothing else. Everything else compares
    normalised.
    """
    if name in PHONE_FIELDS:
        return _digits(expected) == _digits(actual) and bool(_digits(expected))
    return _normalise(expected) == _normalise(actual)


@dataclass(frozen=True, slots=True)
class FieldAccuracy:
    """Per scenario extraction accuracy, and which fields were wrong."""

    accuracy: float
    matched: tuple[str, ...]
    missed: tuple[str, ...]
    excluded: tuple[str, ...]

    @property
    def total_compared(self) -> int:
        return len(self.matched) + len(self.missed)


def field_accuracy(
    expected: dict[str, Any],
    actual: dict[str, Any],
    not_expected: Sequence[str] = (),
) -> FieldAccuracy:
    """Fraction of the persona's expected fields the agent extracted correctly.

    Fields the persona lists in ``not_expected`` are excluded from both halves of the
    fraction: the caller never said them, so neither getting them nor missing them tells
    us anything about extraction.
    """
    excluded = tuple(sorted(set(not_expected)))
    matched: list[str] = []
    missed: list[str] = []
    for name, value in sorted(expected.items()):
        if name in excluded:
            continue
        (matched if field_matches(name, value, actual.get(name)) else missed).append(name)
    total = len(matched) + len(missed)
    return FieldAccuracy(
        accuracy=len(matched) / total if total else 1.0,
        matched=tuple(matched),
        missed=tuple(missed),
        excluded=excluded,
    )


@dataclass(frozen=True, slots=True)
class HandoffCounts:
    """The confusion matrix for the handoff decision."""

    true_positive: int = 0
    false_positive: int = 0
    true_negative: int = 0
    false_negative: int = 0

    @property
    def precision(self) -> float:
        """Of the handoffs triggered, how many should have been. Guards a coordinator's time."""
        predicted = self.true_positive + self.false_positive
        return self.true_positive / predicted if predicted else 1.0

    @property
    def recall(self) -> float:
        """Of the handoffs that should have happened, how many did. Guards revenue."""
        actual = self.true_positive + self.false_negative
        return self.true_positive / actual if actual else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def handoff_counts(pairs: Sequence[tuple[bool, bool]]) -> HandoffCounts:
    """Count (expected, actual) handoff decisions into a confusion matrix."""
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for expected, actual in pairs:
        if expected and actual:
            counts["tp"] += 1
        elif not expected and actual:
            counts["fp"] += 1
        elif not expected and not actual:
            counts["tn"] += 1
        else:
            counts["fn"] += 1
    return HandoffCounts(counts["tp"], counts["fp"], counts["tn"], counts["fn"])


def fallback_activation(
    results: Sequence[tuple[bool, bool]],
) -> dict[str, float]:
    """How often objection handling fired, split by whether it should have.

    ``results`` is (persona_has_an_objection, handler_fired). Firing on a scenario with no
    objection is the expensive error: it derails a conversation that was going fine.
    """
    should = [fired for has, fired in results if has]
    should_not = [fired for has, fired in results if not has]
    return {
        "activation_rate": sum(fired for _, fired in results) / len(results) if results else 0.0,
        "true_activation_rate": sum(should) / len(should) if should else 1.0,
        "false_activation_rate": sum(should_not) / len(should_not) if should_not else 0.0,
    }


REQUIRED_LEAD_FIELDS = (
    "treatment_interest",
    "name",
    "callback_number",
)


def crm_completeness(
    actual: dict[str, Any], required: Sequence[str] = REQUIRED_LEAD_FIELDS
) -> float:
    """Fraction of the fields a coordinator needs that are actually populated.

    A lead record missing the callback number is not a lead. This is separate from
    extraction accuracy: a record can be entirely correct and still be useless.
    """
    if not required:
        return 1.0
    present = sum(1 for name in required if actual.get(name) not in (None, "", []))
    return present / len(required)


def outcome_correct(expected: str, actual: str | None) -> bool:
    return _normalise(expected) == _normalise(actual)


@dataclass(frozen=True, slots=True)
class Spread:
    """A metric reported with its variance, never as a bare number."""

    mean: float
    stdev: float
    minimum: float
    maximum: float
    n: int

    def __str__(self) -> str:
        return f"{self.mean:.3f} +/- {self.stdev:.3f} (n={self.n})"


def spread(values: Sequence[float]) -> Spread:
    """Mean and spread. A single value has zero standard deviation, not an error."""
    if not values:
        return Spread(0.0, 0.0, 0.0, 0.0, 0)
    return Spread(
        mean=statistics.fmean(values),
        stdev=statistics.stdev(values) if len(values) > 1 else 0.0,
        minimum=min(values),
        maximum=max(values),
        n=len(values),
    )


def flaky_scenarios(passes_by_scenario: dict[str, Sequence[bool]]) -> list[str]:
    """Scenarios whose pass or fail flipped between repeats.

    A flaky scenario is not noise to be averaged away. It says the prompt is
    underdetermined at that point, and it is the most useful thing the harness produces.
    """
    return sorted(
        scenario for scenario, passes in passes_by_scenario.items() if len(set(passes)) > 1
    )


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest rank percentile. p is 0 to 100."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(p / 100 * len(ordered) + 0.5) - 1))
    return ordered[index]


@dataclass
class RunSummary:
    """Everything a run reports, per category and overall."""

    scenarios: int = 0
    repeats: int = 0
    passed: int = 0
    field_accuracy: Spread = field(default_factory=lambda: spread([]))
    outcome_accuracy: Spread = field(default_factory=lambda: spread([]))
    crm_completeness: Spread = field(default_factory=lambda: spread([]))
    handle_time_turns: Spread = field(default_factory=lambda: spread([]))
    handoff: HandoffCounts = field(default_factory=HandoffCounts)
    fallback: dict[str, float] = field(default_factory=dict)
    flaky: list[str] = field(default_factory=list)
    by_group: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        total = self.scenarios * self.repeats
        return self.passed / total if total else 0.0
