"""Deterministic lead scoring.

Pure functions, no LLM, no database, no clock. The LLM extracts fields; this module turns
fields into a number and the number into a route. See docs/scoring.md, which this file
reproduces below and must stay in step with.

Rule table, from docs/scoring.md:

    | # | Signal                                              | Points |
    |---|-----------------------------------------------------|--------|
    | 1 | Treatment interest is full arch or multiple implants |    +30 |
    | 2 | Treatment interest is single implant                |    +15 |
    | 3 | Pain level 6 or higher                              |    +20 |
    | 4 | Considering for more than 6 months                  |    +10 |
    | 5 | Has dental insurance, any plan                      |    +15 |
    | 6 | Named an employer or a plan                         |    +10 |
    | 7 | Asked about financing, not just price               |    +10 |
    | 8 | Price objection raised and not recovered            |    -15 |
    | 9 | Just looking, and declined the callback             |    -30 |

    handoff  if score >= threshold and coordinator_available
    callback otherwise
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from arcagent.agent.state import (
    ConsideringDuration,
    LeadFields,
    ObjectionKind,
    TreatmentInterest,
)

DEFAULT_THRESHOLD = 60

PAIN_THRESHOLD = 6
HIGH_VALUE_TREATMENTS = frozenset(
    {TreatmentInterest.FULL_ARCH, TreatmentInterest.MULTIPLE_IMPLANTS}
)


class Decision(enum.StrEnum):
    HANDOFF = "handoff"
    CALLBACK = "callback"


class Rule(NamedTuple):
    """One row of the table: a name, the points it is worth, and when it fires."""

    name: str
    points: int
    applies: Callable[[LeadFields], bool]


def _high_value_treatment(fields: LeadFields) -> bool:
    return fields.treatment_interest in HIGH_VALUE_TREATMENTS


def _single_implant(fields: LeadFields) -> bool:
    return fields.treatment_interest is TreatmentInterest.SINGLE_IMPLANT


def _in_pain(fields: LeadFields) -> bool:
    return fields.pain_level is not None and fields.pain_level >= PAIN_THRESHOLD


def _considering_a_long_time(fields: LeadFields) -> bool:
    return fields.considering_duration is ConsideringDuration.OVER_6_MONTHS


def _has_insurance(fields: LeadFields) -> bool:
    return fields.has_insurance is True


def _named_employer_or_plan(fields: LeadFields) -> bool:
    return bool((fields.employer_name or "").strip() or (fields.plan_type or "").strip())


def _asked_about_financing(fields: LeadFields) -> bool:
    return fields.financing_asked is True


def _unrecovered_price_objection(fields: LeadFields) -> bool:
    objection = fields.objection(ObjectionKind.PRICE)
    return objection is not None and not objection.recovered


def _browsing_and_declined_callback(fields: LeadFields) -> bool:
    return fields.objection(ObjectionKind.JUST_LOOKING) is not None and fields.callback_declined


RULES: Sequence[Rule] = (
    Rule("full_arch_or_multiple", 30, _high_value_treatment),
    Rule("single_implant", 15, _single_implant),
    Rule("pain_6_or_higher", 20, _in_pain),
    Rule("considering_over_6_months", 10, _considering_a_long_time),
    Rule("has_insurance", 15, _has_insurance),
    Rule("named_employer_or_plan", 10, _named_employer_or_plan),
    Rule("asked_about_financing", 10, _asked_about_financing),
    Rule("unrecovered_price_objection", -15, _unrecovered_price_objection),
    Rule("just_looking_declined_callback", -30, _browsing_and_declined_callback),
)


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """A score, the rules that produced it, and the route it implies."""

    score: int
    breakdown: dict[str, int]
    decision: Decision
    threshold_used: int
    coordinator_available: bool

    @property
    def is_handoff(self) -> bool:
        return self.decision is Decision.HANDOFF


def score(
    fields: LeadFields,
    threshold: int = DEFAULT_THRESHOLD,
    coordinator_available: bool = True,
) -> ScoreResult:
    """Score a lead and choose its route.

    Args:
        fields: everything the conversation extracted.
        threshold: handoff cutoff, inclusive. A score equal to it is a handoff.
        coordinator_available: whether a human is there to take the transfer. False always
            routes to a callback, whatever the score, because a transfer nobody answers is
            worse for the caller than a booked callback.

    Returns:
        The score, the per rule breakdown of only the rules that fired, and the decision.
    """
    breakdown = {rule.name: rule.points for rule in RULES if rule.applies(fields)}
    total = sum(breakdown.values())
    decision = (
        Decision.HANDOFF if total >= threshold and coordinator_available else Decision.CALLBACK
    )
    return ScoreResult(
        score=total,
        breakdown=breakdown,
        decision=decision,
        threshold_used=threshold,
        coordinator_available=coordinator_available,
    )
