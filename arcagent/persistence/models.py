"""SQLAlchemy models. Schema follows section 5 of the scope document.

PII rules baked into the schema:
  - ``calls`` stores a hash of the caller's number, never the number
  - the caller's real number and name live only in ``leads``
  - no audio is stored, only transcripts, and those are subject to the retention job
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# JSONB on Postgres, plain JSON elsewhere so the suite can run on SQLite.
JsonCol = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Outcome(enum.StrEnum):
    HANDOFF = "handoff"
    CALLBACK_BOOKED = "callback_booked"
    WRONG_NUMBER = "wrong_number"
    LANGUAGE_FALLBACK = "language_fallback"
    ABANDONED = "abandoned"
    NOT_A_LEAD = "not_a_lead"


class Speaker(enum.StrEnum):
    AGENT = "agent"
    CALLER = "caller"


class Decision(enum.StrEnum):
    HANDOFF = "handoff"
    CALLBACK = "callback"


class Tier(enum.StrEnum):
    TEXT = "text"
    AUDIO = "audio"


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    twilio_call_sid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    from_number_hash: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[Outcome | None] = mapped_column(Enum(Outcome, name="call_outcome"))
    final_node: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(8), default="en")

    turns: Mapped[list[Turn]] = relationship(back_populates="call", cascade="all, delete-orphan")
    lead: Mapped[Lead | None] = relationship(back_populates="call", cascade="all, delete-orphan")


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    turn_index: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[Speaker] = mapped_column(Enum(Speaker, name="turn_speaker"))
    text: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Latency budget, milliseconds. Null means the stage did not run on this turn.
    stt_final_ms: Mapped[int | None] = mapped_column(Integer)
    llm_ttft_ms: Mapped[int | None] = mapped_column(Integer)
    tts_first_byte_ms: Mapped[int | None] = mapped_column(Integer)
    playback_start_ms: Mapped[int | None] = mapped_column(Integer)

    interrupted: Mapped[bool] = mapped_column(Boolean, default=False)
    node_name: Mapped[str | None] = mapped_column(String(64))

    call: Mapped[Call] = relationship(back_populates="turns")


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    name: Mapped[str | None] = mapped_column(String(128))
    callback_number: Mapped[str | None] = mapped_column(String(32))
    preferred_time: Mapped[str | None] = mapped_column(String(64))

    treatment_interest: Mapped[str | None] = mapped_column(String(32))
    missing_teeth_count: Mapped[int | None] = mapped_column(Integer)
    pain_level: Mapped[int | None] = mapped_column(Integer)
    considering_duration: Mapped[str | None] = mapped_column(String(32))

    has_insurance: Mapped[bool | None] = mapped_column(Boolean)
    employer_name: Mapped[str | None] = mapped_column(String(128))
    plan_type: Mapped[str | None] = mapped_column(String(64))
    coverage_awareness: Mapped[str | None] = mapped_column(String(32))

    objections: Mapped[list | None] = mapped_column(JsonCol, default=list)
    financing_asked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    call: Mapped[Call] = relationship(back_populates="lead")
    scores: Mapped[list[LeadScore]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )
    callbacks: Mapped[list[Callback]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )


class LeadScore(Base):
    __tablename__ = "lead_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    threshold_used: Mapped[int] = mapped_column(Integer)
    decision: Mapped[Decision] = mapped_column(Enum(Decision, name="score_decision"))
    score_breakdown: Mapped[dict | None] = mapped_column(JsonCol, default=dict)

    lead: Mapped[Lead] = relationship(back_populates="scores")


class Slot(Base):
    """A bookable callback window. Seeded by scripts/seed_slots.py."""

    __tablename__ = "slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    slot_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    booked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class Callback(Base):
    __tablename__ = "callbacks"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sms_sid: Mapped[str | None] = mapped_column(String(64))
    sms_status: Mapped[str | None] = mapped_column(String(32))
    # TCPA: the caller asked for this. Record when, so consent is evidenced.
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_turn_index: Mapped[int | None] = mapped_column(Integer)

    lead: Mapped[Lead] = relationship(back_populates="callbacks")


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_name: Mapped[str] = mapped_column(String(128), index=True)
    git_sha: Mapped[str] = mapped_column(String(40))
    prompt_version: Mapped[str] = mapped_column(String(16))
    threshold: Mapped[int] = mapped_column(Integer)
    tier: Mapped[Tier] = mapped_column(Enum(Tier, name="eval_tier"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    results: Mapped[list[EvalResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True)
    scenario_id: Mapped[str] = mapped_column(String(64), index=True)
    repeat_index: Mapped[int] = mapped_column(Integer, default=0)
    expected: Mapped[dict | None] = mapped_column(JsonCol, default=dict)
    actual: Mapped[dict | None] = mapped_column(JsonCol, default=dict)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    field_accuracy: Mapped[float | None] = mapped_column(Float)
    handoff_expected: Mapped[bool | None] = mapped_column(Boolean)
    handoff_actual: Mapped[bool | None] = mapped_column(Boolean)
    fallback_activated: Mapped[bool | None] = mapped_column(Boolean)
    handle_time_s: Mapped[float | None] = mapped_column(Float)
    crm_completeness: Mapped[float | None] = mapped_column(Float)
    latency_p50_ms: Mapped[int | None] = mapped_column(Integer)
    latency_p95_ms: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    run: Mapped[EvalRun] = relationship(back_populates="results")
