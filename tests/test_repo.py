"""Repository behaviour, including the PII rules the schema is supposed to enforce."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from arcagent.logging import hash_number
from arcagent.persistence.models import Decision, Lead, Outcome, Slot, Speaker, Tier
from arcagent.persistence.repo import CallRepository, EvalRepository

CALLER = "+14155550123"


class TestCalls:
    def test_the_callers_number_is_hashed_never_stored(self, db_session: Session) -> None:
        repo = CallRepository(db_session)
        call = repo.start_call("CA_test", CALLER)
        assert call.from_number_hash == hash_number(CALLER)
        assert CALLER not in str(call.from_number_hash)

    def test_the_same_caller_hashes_the_same_way_across_calls(self, db_session: Session) -> None:
        repo = CallRepository(db_session)
        first = repo.start_call("CA_1", CALLER)
        second = repo.start_call("CA_2", CALLER)
        assert first.from_number_hash == second.from_number_hash

    def test_lookup_by_twilio_sid(self, db_session: Session) -> None:
        repo = CallRepository(db_session)
        repo.start_call("CA_test", CALLER)
        assert repo.get_call_by_sid("CA_test") is not None
        assert repo.get_call_by_sid("CA_missing") is None

    def test_end_call_sets_outcome_and_duration(self, db_session: Session) -> None:
        repo = CallRepository(db_session)
        call = repo.start_call("CA_test", CALLER)
        call.started_at = datetime.now(UTC) - timedelta(seconds=90)
        ended = repo.end_call(call.id, Outcome.HANDOFF, final_node="warm_transfer")
        assert ended.outcome is Outcome.HANDOFF
        assert ended.final_node == "warm_transfer"
        assert 89 <= (ended.duration_s or 0) <= 92

    def test_ending_an_unknown_call_raises(self, db_session: Session) -> None:
        with pytest.raises(LookupError):
            CallRepository(db_session).end_call(999, Outcome.ABANDONED)


class TestTurns:
    def test_latency_columns_are_written_from_the_timings_mapping(
        self, db_session: Session
    ) -> None:
        repo = CallRepository(db_session)
        call = repo.start_call("CA_test", CALLER)
        turn = repo.add_turn(
            call.id,
            0,
            Speaker.AGENT,
            "hello",
            latency={
                "stt_final_ms": 250,
                "llm_ttft_ms": 300,
                "tts_first_byte_ms": 120,
                "playback_start_ms": 80,
            },
            node_name="greet_and_disclose",
        )
        assert turn.stt_final_ms == 250
        assert turn.llm_ttft_ms == 300
        assert turn.tts_first_byte_ms == 120
        assert turn.playback_start_ms == 80
        assert turn.node_name == "greet_and_disclose"

    def test_a_missing_stage_stays_null(self, db_session: Session) -> None:
        repo = CallRepository(db_session)
        call = repo.start_call("CA_test", CALLER)
        turn = repo.add_turn(call.id, 0, Speaker.CALLER, "hi", latency={"stt_final_ms": 200})
        assert turn.stt_final_ms == 200
        assert turn.llm_ttft_ms is None

    def test_interrupted_turns_are_flagged(self, db_session: Session) -> None:
        repo = CallRepository(db_session)
        call = repo.start_call("CA_test", CALLER)
        turn = repo.add_turn(call.id, 1, Speaker.AGENT, "and we also", interrupted=True)
        assert turn.interrupted


class TestLeadsAndScores:
    def test_save_lead_creates_then_updates(self, db_session: Session) -> None:
        repo = CallRepository(db_session)
        call = repo.start_call("CA_test", CALLER)
        lead = repo.save_lead(call.id, {"treatment_interest": "full_arch", "pain_level": 7})
        again = repo.save_lead(call.id, {"has_insurance": True, "employer_name": "Acme"})
        assert lead.id == again.id
        assert again.treatment_interest == "full_arch"
        assert again.has_insurance is True
        assert db_session.query(Lead).count() == 1

    def test_unknown_fields_are_ignored_rather_than_crashing_a_live_call(
        self, db_session: Session
    ) -> None:
        repo = CallRepository(db_session)
        call = repo.start_call("CA_test", CALLER)
        lead = repo.save_lead(call.id, {"pain_level": 3, "invented_by_the_llm": "nonsense"})
        assert lead.pain_level == 3
        assert not hasattr(lead, "invented_by_the_llm")

    def test_objections_round_trip_as_json(self, db_session: Session) -> None:
        repo = CallRepository(db_session)
        call = repo.start_call("CA_test", CALLER)
        lead = repo.save_lead(call.id, {"objections": ["price", "fear"]})
        db_session.commit()
        db_session.expire_all()
        assert db_session.get(Lead, lead.id).objections == ["price", "fear"]

    def test_score_stores_the_threshold_it_was_judged_against(self, db_session: Session) -> None:
        repo = CallRepository(db_session)
        call = repo.start_call("CA_test", CALLER)
        lead = repo.save_lead(call.id, {})
        score = repo.save_score(
            lead.id, 75, 60, Decision.HANDOFF, {"treatment_interest": 30, "pain": 20}
        )
        assert score.score == 75
        assert score.threshold_used == 60
        assert score.decision is Decision.HANDOFF
        assert score.score_breakdown["pain"] == 20


class TestCallbacks:
    def _slots(self, db_session: Session, count: int = 3) -> list[Slot]:
        base = datetime.now(UTC) + timedelta(hours=1)
        slots = [
            Slot(
                slot_start=base + timedelta(hours=i), slot_end=base + timedelta(hours=i, minutes=30)
            )
            for i in range(count)
        ]
        db_session.add_all(slots)
        db_session.flush()
        return slots

    def test_next_open_slot_is_the_earliest_unbooked_future_slot(self, db_session: Session) -> None:
        repo = CallRepository(db_session)
        slots = self._slots(db_session)
        slots[0].booked = True
        db_session.flush()
        assert repo.next_open_slot().id == slots[1].id

    def test_booking_marks_the_slot_and_records_consent(self, db_session: Session) -> None:
        repo = CallRepository(db_session)
        call = repo.start_call("CA_test", CALLER)
        lead = repo.save_lead(call.id, {})
        slot = self._slots(db_session)[0]
        callback = repo.book_callback(lead.id, slot, consent_turn_index=6)
        assert slot.booked
        assert callback.consent_at is not None
        assert callback.consent_turn_index == 6

    def test_no_slots_returns_none_rather_than_raising(self, db_session: Session) -> None:
        assert CallRepository(db_session).next_open_slot() is None

    def test_sms_status_is_recorded(self, db_session: Session) -> None:
        repo = CallRepository(db_session)
        call = repo.start_call("CA_test", CALLER)
        lead = repo.save_lead(call.id, {})
        callback = repo.book_callback(lead.id, self._slots(db_session)[0])
        updated = repo.record_sms(callback.id, "SM_test", "queued")
        assert updated.sms_sid == "SM_test"
        assert updated.sms_status == "queued"


class TestEvalRepository:
    def test_a_run_records_the_git_sha_and_prompt_version(self, db_session: Session) -> None:
        repo = EvalRepository(db_session)
        run = repo.create_run("baseline", "abc1234", "v1", 60, Tier.TEXT)
        assert run.git_sha == "abc1234"
        assert run.prompt_version == "v1"
        assert run.tier is Tier.TEXT

    def test_results_are_grouped_by_run(self, db_session: Session) -> None:
        repo = EvalRepository(db_session)
        first = repo.create_run("a", "sha1", "v1", 60, Tier.TEXT)
        second = repo.create_run("b", "sha2", "v1", 60, Tier.TEXT)
        repo.add_result(first.id, scenario_id="hot_1", passed=True)
        repo.add_result(first.id, scenario_id="hot_2", passed=False)
        repo.add_result(second.id, scenario_id="hot_1", passed=True)
        assert len(repo.results_for(first.id)) == 2
        assert len(repo.results_for(second.id)) == 1


class TestPersistenceSink:
    """The sink that writes a live call, driven off the Twilio start event."""

    async def test_the_start_event_creates_the_call_row(self, tmp_path) -> None:
        from arcagent.persistence.db import get_engine, get_session_factory
        from arcagent.persistence.models import Base, Call
        from arcagent.telephony.call_session import TurnRecord
        from arcagent.telephony.persistence_sink import DatabaseTurnSink
        from arcagent.telephony.twilio_stream import parse_event
        from tests.fakes import start_message

        url = f"sqlite:///{tmp_path / 'sink.db'}"
        Base.metadata.create_all(get_engine(url))

        message = start_message()
        message["start"]["customParameters"] = {"call_sid": "CA_sink", "from": CALLER}
        sink = DatabaseTurnSink(database_url=url)
        await sink.open(parse_event(message))
        await sink(TurnRecord(speaker="caller", text="hello", latency={"stt_final_ms": 210}))
        await sink(TurnRecord(speaker="agent", text="hi", latency={"tts_first_byte_ms": 90}))
        await sink.close(Outcome.CALLBACK_BOOKED, final_node="book_callback_and_sms")

        session = get_session_factory(url)()
        try:
            call = session.query(Call).one()
            assert call.from_number_hash == hash_number(CALLER)
            assert call.outcome is Outcome.CALLBACK_BOOKED
            assert call.final_node == "book_callback_and_sms"
            assert [t.turn_index for t in call.turns] == [0, 1]
            assert call.turns[0].stt_final_ms == 210
            assert call.turns[1].tts_first_byte_ms == 90
        finally:
            session.close()

    async def test_a_sink_that_never_opened_swallows_turns(self) -> None:
        from arcagent.telephony.call_session import TurnRecord
        from arcagent.telephony.persistence_sink import DatabaseTurnSink

        sink = DatabaseTurnSink(database_url="sqlite://")
        await sink(TurnRecord(speaker="caller", text="hello"))
        await sink.close(Outcome.ABANDONED)
