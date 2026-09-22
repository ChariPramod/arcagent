"""Repository: the only module that writes call data.

Everything here takes plain values and returns model instances. No module outside
persistence/ builds a SQLAlchemy statement, which keeps the schema changeable in one place.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arcagent.logging import get_logger, hash_number
from arcagent.persistence.models import (
    Call,
    Callback,
    Decision,
    EvalResult,
    EvalRun,
    Lead,
    LeadScore,
    Outcome,
    Slot,
    Speaker,
    Tier,
    Turn,
)
from arcagent.persistence.transfer_models import TransferAttempt

log = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


class CallRepository:
    """Writes for one call. Hold one per session; it is not thread safe."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def start_call(self, twilio_call_sid: str, from_number: str, language: str = "en") -> Call:
        """Create the call row. The caller's number is hashed here and never stored raw."""
        call = Call(
            twilio_call_sid=twilio_call_sid,
            from_number_hash=hash_number(from_number),
            started_at=_now(),
            language=language,
        )
        self.session.add(call)
        self.session.flush()
        return call

    def get_call_by_sid(self, twilio_call_sid: str) -> Call | None:
        return self.session.scalar(select(Call).where(Call.twilio_call_sid == twilio_call_sid))

    def add_turn(
        self,
        call_id: int,
        turn_index: int,
        speaker: Speaker | str,
        text: str,
        latency: Mapping[str, int | None] | None = None,
        interrupted: bool = False,
        node_name: str | None = None,
    ) -> Turn:
        """Append a turn. ``latency`` is ``TurnTimings.as_columns()``."""
        latency = latency or {}
        turn = Turn(
            call_id=call_id,
            turn_index=turn_index,
            speaker=Speaker(speaker),
            text=text,
            started_at=_now(),
            stt_final_ms=latency.get("stt_final_ms"),
            llm_ttft_ms=latency.get("llm_ttft_ms"),
            tts_first_byte_ms=latency.get("tts_first_byte_ms"),
            playback_start_ms=latency.get("playback_start_ms"),
            interrupted=interrupted,
            node_name=node_name,
        )
        self.session.add(turn)
        self.session.flush()
        return turn

    def end_call(
        self,
        call_id: int,
        outcome: Outcome | str,
        final_node: str | None = None,
        language: str | None = None,
    ) -> Call:
        call = self.session.scalar(
            select(Call)
            .where(Call.id == call_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if call is None:
            raise LookupError(f"call {call_id} not found")
        # Transfer callbacks own the terminal state. The session may close before
        # callbacks arrive or after they commit; neither case may overwrite evidence.
        if self.session.scalar(
            select(TransferAttempt.id).where(TransferAttempt.call_id == call_id)
        ):
            return call
        call.ended_at = _now()
        started = call.started_at
        if started is not None:
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            call.duration_s = (call.ended_at - started).total_seconds()
        call.outcome = Outcome(outcome)
        if final_node is not None:
            call.final_node = final_node
        if language is not None:
            call.language = language
        self.session.flush()
        return call

    def save_lead(self, call_id: int, fields: Mapping[str, Any]) -> Lead:
        """Create or update the lead for a call from extracted agent state."""
        lead = self.session.scalar(select(Lead).where(Lead.call_id == call_id))
        if lead is None:
            lead = Lead(call_id=call_id)
            self.session.add(lead)
        allowed = {c.name for c in Lead.__table__.columns} - {"id", "call_id", "created_at"}
        for key, value in fields.items():
            if key in allowed:
                setattr(lead, key, value)
        self.session.flush()
        return lead

    def save_score(
        self,
        lead_id: int,
        score: int,
        threshold_used: int,
        decision: Decision | str,
        breakdown: Mapping[str, Any] | None = None,
    ) -> LeadScore:
        row = LeadScore(
            lead_id=lead_id,
            score=score,
            threshold_used=threshold_used,
            decision=Decision(decision),
            score_breakdown=dict(breakdown or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def next_open_slot(self, after: datetime | None = None) -> Slot | None:
        after = after or _now()
        return self.session.scalar(
            select(Slot)
            .where(Slot.booked.is_(False), Slot.slot_start > after)
            .order_by(Slot.slot_start)
            .limit(1)
        )

    def book_callback(
        self,
        lead_id: int,
        slot: Slot,
        consent_turn_index: int | None = None,
    ) -> Callback:
        slot.booked = True
        callback = Callback(
            lead_id=lead_id,
            slot_start=slot.slot_start,
            consent_at=_now(),
            consent_turn_index=consent_turn_index,
        )
        self.session.add(callback)
        self.session.flush()
        return callback

    def record_sms(self, callback_id: int, sms_sid: str, sms_status: str) -> Callback:
        callback = self.session.get(Callback, callback_id)
        if callback is None:
            raise LookupError(f"callback {callback_id} not found")
        callback.sms_sid = sms_sid
        callback.sms_status = sms_status
        self.session.flush()
        return callback


class EvalRepository:
    """Writes for the evaluation harness."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(
        self,
        run_name: str,
        git_sha: str,
        prompt_version: str,
        threshold: int,
        tier: Tier | str,
        snapshot: dict | None = None,
    ) -> EvalRun:
        run = EvalRun(
            run_name=run_name,
            git_sha=git_sha,
            prompt_version=prompt_version,
            threshold=threshold,
            tier=Tier(tier),
            snapshot=snapshot,
            created_at=_now(),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def add_result(self, run_id: int, **fields: Any) -> EvalResult:
        result = EvalResult(run_id=run_id, **fields)
        self.session.add(result)
        self.session.flush()
        return result

    def get_run(self, run_id: int) -> EvalRun | None:
        return self.session.get(EvalRun, run_id)

    def results_for(self, run_id: int) -> list[EvalResult]:
        return list(
            self.session.scalars(select(EvalResult).where(EvalResult.run_id == run_id)).all()
        )
