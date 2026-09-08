"""Per node structured output schemas.

Each node's schema carries only the fields that node owns, plus ``next_utterance``. One
node cannot overwrite another node's extraction, because the field is not in its schema.

Every extracted field is optional. A caller who has not answered yet produces null, and
null never overwrites a value already in state. That rule lives in
``arcagent/agent/nodes/base.py`` and is what stops a later turn from erasing an earlier
answer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from arcagent.agent.state import (
    ConsideringDuration,
    CoverageAwareness,
    ObjectionKind,
    TreatmentInterest,
)


class NodeOutput(BaseModel):
    """Base for every node schema. ``next_utterance`` is what the agent says out loud."""

    model_config = {"extra": "forbid"}

    next_utterance: str = Field(description="What the agent says next. One or two sentences.")


class TreatmentInterestOutput(NodeOutput):
    treatment_interest: TreatmentInterest | None = Field(
        default=None, description="Null until the caller has made it clear."
    )


class SituationOutput(NodeOutput):
    missing_teeth_count: int | None = Field(default=None, ge=0, le=32)
    pain_level: int | None = Field(default=None, ge=0, le=10)
    considering_duration: ConsideringDuration | None = None


class InsuranceOutput(NodeOutput):
    has_insurance: bool | None = None
    employer_name: str | None = None
    plan_type: str | None = None
    coverage_awareness: CoverageAwareness | None = None


class ContactOutput(NodeOutput):
    name: str | None = None
    callback_number: str | None = Field(
        default=None, description="Digits only. Null if the caller declined to give one."
    )
    preferred_time: str | None = None
    callback_declined: bool = False


class ObjectionOutput(NodeOutput):
    """Whether the objection was handled, which is what scoring rule 8 turns on."""

    recovered: bool = Field(
        default=False,
        description="True only when the caller has moved on from the objection.",
    )


class ObjectionDetection(BaseModel):
    """The classifier that can redirect any node into objection handling."""

    model_config = {"extra": "forbid"}

    objection: ObjectionKind | None = Field(
        default=None, description="Null when the caller raised no objection."
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
