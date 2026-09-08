"""Conversation state and the field vocabularies from docs/scoring.md.

Every value the LLM is allowed to produce for an enum field is declared here. A node that
returns something outside the vocabulary is a bug in the prompt, and the graph rejects it
rather than letting a made up value reach the scorer.
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from typing import Any


class TreatmentInterest(enum.StrEnum):
    FULL_ARCH = "full_arch"
    MULTIPLE_IMPLANTS = "multiple_implants"
    SINGLE_IMPLANT = "single_implant"
    CONSULTATION_ONLY = "consultation_only"
    NOT_SURE = "not_sure"
    WRONG_NUMBER = "wrong_number"


class ConsideringDuration(enum.StrEnum):
    UNDER_1_MONTH = "under_1_month"
    ONE_TO_6_MONTHS = "one_to_6_months"
    OVER_6_MONTHS = "over_6_months"
    UNKNOWN = "unknown"


class CoverageAwareness(enum.StrEnum):
    KNOWS_NOT_COVERED = "knows_not_covered"
    THINKS_COVERED = "thinks_covered"
    UNSURE = "unsure"


class ObjectionKind(enum.StrEnum):
    PRICE = "price"
    FEAR = "fear"
    JUST_LOOKING = "just_looking"
    SPOUSE = "spouse"
    BAD_EXPERIENCE = "bad_experience"


@dataclass(frozen=True, slots=True)
class Objection:
    """One objection, and whether the agent brought the caller back from it.

    ``recovered`` is what rule 8 turns on: raising a price objection is normal and costs
    nothing, staying stuck on it is what marks a lead cold.
    """

    kind: ObjectionKind
    recovered: bool = False
    turn_index: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"kind": str(self.kind), "recovered": self.recovered, "turn_index": self.turn_index}


@dataclass(slots=True)
class LeadFields:
    """Everything the conversation extracts, and nothing it does not.

    This is the only input to scoring. Keeping it a plain dataclass rather than the graph's
    full state means the scorer can be tested with no graph, no LLM and no database.
    """

    treatment_interest: TreatmentInterest | None = None
    missing_teeth_count: int | None = None
    pain_level: int | None = None
    considering_duration: ConsideringDuration | None = None

    has_insurance: bool | None = None
    employer_name: str | None = None
    plan_type: str | None = None
    coverage_awareness: CoverageAwareness | None = None

    financing_asked: bool = False
    callback_declined: bool = False
    objections: list[Objection] = field(default_factory=list)

    name: str | None = None
    callback_number: str | None = None
    preferred_time: str | None = None

    def objection(self, kind: ObjectionKind) -> Objection | None:
        """The most recent objection of this kind, if the caller raised one."""
        for item in reversed(self.objections):
            if item.kind is kind:
                return item
        return None

    def as_lead_row(self) -> dict[str, Any]:
        """Column values for the ``leads`` table. Enums become their string values."""
        row = asdict(self)
        row.pop("callback_declined")
        row["objections"] = [o.as_dict() for o in self.objections]
        for key in ("treatment_interest", "considering_duration", "coverage_awareness"):
            if row[key] is not None:
                row[key] = str(row[key])
        return row
