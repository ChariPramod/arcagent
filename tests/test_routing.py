"""Warm transfer, callback booking, and the SMS, against a mocked Twilio client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from arcagent.agent.scoring import Decision
from arcagent.agent.state import LeadFields, Objection, ObjectionKind, TreatmentInterest
from arcagent.config import Settings
from arcagent.persistence.db import get_engine, get_session_factory
from arcagent.persistence.models import Base, Callback, Lead, LeadScore, Outcome, Slot
from arcagent.persistence.repo import CallRepository
from arcagent.telephony.routing import CallRouter
from arcagent.telephony.twilio_actions import (
    OPT_OUT_LINE,
    SmsFailed,
    TransferFailed,
    TwilioActions,
    callback_message,
    format_slot,
)

COORDINATOR = "+15550001111"
TWILIO_NUMBER = "+15550002222"
CALLER = "+14155550123"
ATTEMPT = "de38285a-f144-4f71-a5e9-6f72cd681d48"


class FakeCall:
    def __init__(self, sid: str, parent: FakeTwilioClient) -> None:
        self.sid = sid
        self._parent = parent

    def update(self, **kwargs: Any) -> None:
        if self._parent.fail_calls:
            raise RuntimeError("twilio said no")
        self._parent.call_updates.append((self.sid, kwargs))


class FakeMessages:
    def __init__(self, parent: FakeTwilioClient) -> None:
        self._parent = parent

    def create(self, **kwargs: Any) -> Any:
        if self._parent.fail_messages:
            raise RuntimeError("twilio said no")
        self._parent.messages_sent.append(kwargs)

        class Sent:
            sid = "SM_test_sid"
            status = "queued"

        return Sent()


class FakeTwilioClient:
    def __init__(self, fail_calls: bool = False, fail_messages: bool = False) -> None:
        self.call_updates: list[tuple[str, dict]] = []
        self.messages_sent: list[dict] = []
        self.fail_calls = fail_calls
        self.fail_messages = fail_messages

    def calls(self, sid: str) -> FakeCall:
        return FakeCall(sid, self)

    @property
    def messages(self) -> FakeMessages:
        return FakeMessages(self)


def settings(**overrides: Any) -> Settings:
    base = {
        "coordinator_number": COORDINATOR,
        "twilio_number": TWILIO_NUMBER,
        "twilio_account_sid": "AC_test",
        "twilio_auth_token": "token_test",
        "public_url": "https://voice.example.test",
    }
    return Settings(_env_file=None, **(base | overrides))


class TestTransfer:
    def test_the_live_call_is_updated_with_dial_twiml(self) -> None:
        client = FakeTwilioClient()
        twiml = TwilioActions(settings(), client).warm_transfer("CA_live", attempt_id=ATTEMPT)
        assert len(client.call_updates) == 1
        sid, kwargs = client.call_updates[0]
        assert sid == "CA_live"
        assert kwargs["twiml"] == twiml
        assert f">{COORDINATOR}</Number>" in twiml
        assert f"/voice/transfer/{ATTEMPT}/action" in twiml
        assert 'statusCallbackEvent="initiated ringing answered completed"' in twiml

    def test_an_explicit_number_overrides_the_configured_one(self) -> None:
        client = FakeTwilioClient()
        twiml = TwilioActions(settings(), client).warm_transfer(
            "CA_live", "+15559998888", attempt_id=ATTEMPT
        )
        assert ">+15559998888</Number>" in twiml

    def test_no_configured_number_fails_loudly(self) -> None:
        actions = TwilioActions(settings(coordinator_number=""), FakeTwilioClient())
        with pytest.raises(TransferFailed, match="COORDINATOR_NUMBER"):
            actions.warm_transfer("CA_live", attempt_id=ATTEMPT)

    def test_a_twilio_error_becomes_transfer_failed(self) -> None:
        actions = TwilioActions(settings(), FakeTwilioClient(fail_calls=True))
        with pytest.raises(TransferFailed):
            actions.warm_transfer("CA_live", attempt_id=ATTEMPT)


class TestCallbackSms:
    SLOT = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)

    def test_the_body_carries_the_slot_and_the_opt_out_line(self) -> None:
        body = callback_message(self.SLOT)
        assert OPT_OUT_LINE in body
        assert "Tuesday September 15" in body
        assert "2pm" in body

    def test_the_body_says_nothing_clinical_and_names_nobody(self) -> None:
        """A text is read on a lock screen by whoever is holding the phone."""
        body = callback_message(self.SLOT).lower()
        for leak in ("implant", "surgery", "dental", "tooth", "teeth", "procedure"):
            assert leak not in body

    def test_slot_formatting_drops_the_leading_zero(self) -> None:
        assert format_slot(datetime(2026, 9, 15, 9, 0, tzinfo=UTC)).endswith("9am")
        assert format_slot(datetime(2026, 9, 15, 12, 0, tzinfo=UTC)).endswith("12pm")

    def test_the_message_goes_from_the_configured_number(self) -> None:
        client = FakeTwilioClient()
        receipt = TwilioActions(settings(), client).send_callback_sms(CALLER, self.SLOT)
        sent = client.messages_sent[0]
        assert sent["to"] == CALLER
        assert sent["from_"] == TWILIO_NUMBER
        assert OPT_OUT_LINE in sent["body"]
        assert receipt.sid == "SM_test_sid"
        assert receipt.status == "queued"

    def test_no_from_number_fails_loudly(self) -> None:
        actions = TwilioActions(settings(twilio_number=""), FakeTwilioClient())
        with pytest.raises(SmsFailed, match="TWILIO_NUMBER"):
            actions.send_callback_sms(CALLER, self.SLOT)

    def test_a_twilio_error_becomes_sms_failed(self) -> None:
        actions = TwilioActions(settings(), FakeTwilioClient(fail_messages=True))
        with pytest.raises(SmsFailed):
            actions.send_callback_sms(CALLER, self.SLOT)


HOT = LeadFields(
    treatment_interest=TreatmentInterest.FULL_ARCH,
    pain_level=8,
    has_insurance=True,
    employer_name="Acme",
    name="Bob Reyes",
    callback_number=CALLER,
)
COLD = LeadFields(
    treatment_interest=TreatmentInterest.SINGLE_IMPLANT,
    objections=[Objection(ObjectionKind.PRICE)],
    name="Sam",
    callback_number=CALLER,
)


@pytest.fixture
def routed(tmp_path: Path):
    """A router wired to a fresh SQLite database with slots already seeded."""

    def build(client: FakeTwilioClient | None = None, seed_slots: bool = True, **config: Any):
        url = f"sqlite:///{tmp_path / 'routing.db'}"
        Base.metadata.create_all(get_engine(url))
        factory = get_session_factory(url)
        session = factory()
        try:
            call = CallRepository(session).start_call("CA_route", CALLER)
            call_id = call.id
            if seed_slots:
                base = datetime.now(UTC) + timedelta(hours=2)
                session.add_all(
                    Slot(
                        slot_start=base + timedelta(hours=i),
                        slot_end=base + timedelta(hours=i, minutes=30),
                    )
                    for i in range(3)
                )
            session.commit()
        finally:
            session.close()
        client = client or FakeTwilioClient()
        router = CallRouter(
            settings(**config), TwilioActions(settings(**config), client), database_url=url
        )
        return router, client, call_id, factory

    return build


class TestEndOfCallRouting:
    async def test_a_hot_lead_is_persisted_scored_and_transferred(self, routed) -> None:
        router, client, call_id, factory = routed()
        result = await router.finish_call(call_id, "CA_route", HOT)

        assert result.score.score == 75
        assert result.score.decision is Decision.HANDOFF
        assert result.outcome is None
        assert result.succeeded
        assert len(client.call_updates) == 1
        assert client.messages_sent == []

        session = factory()
        try:
            lead = session.query(Lead).one()
            assert lead.name == "Bob Reyes"
            row = session.query(LeadScore).one()
            assert row.score == 75
            assert row.threshold_used == 60
            assert row.score_breakdown["full_arch_or_multiple"] == 30
            assert session.query(Callback).count() == 0
        finally:
            session.close()

    async def test_a_cold_lead_books_a_slot_and_gets_a_text(self, routed) -> None:
        router, client, call_id, factory = routed()
        result = await router.finish_call(call_id, "CA_route", COLD, consent_turn_index=7)

        assert result.score.decision is Decision.CALLBACK
        assert result.outcome is Outcome.CALLBACK_BOOKED
        assert result.slot_start is not None
        assert result.sms_sid == "SM_test_sid"
        assert client.call_updates == []
        assert OPT_OUT_LINE in client.messages_sent[0]["body"]

        session = factory()
        try:
            callback = session.query(Callback).one()
            assert callback.sms_sid == "SM_test_sid"
            assert callback.sms_status == "queued"
            assert callback.consent_at is not None
            assert callback.consent_turn_index == 7
            assert session.query(Slot).filter(Slot.booked.is_(True)).count() == 1
        finally:
            session.close()

    async def test_the_lead_is_saved_even_when_the_transfer_fails(self, routed) -> None:
        """A failed transfer must not lose the lead. A human can still pick it up."""
        router, _client, call_id, factory = routed(FakeTwilioClient(fail_calls=True))
        result = await router.finish_call(call_id, "CA_route", HOT)

        assert not result.succeeded
        assert result.outcome is None  # transport errors may have applied the update
        session = factory()
        try:
            assert session.query(Lead).count() == 1
            assert session.query(LeadScore).one().score == 75
        finally:
            session.close()

    async def test_the_callback_stands_even_when_the_text_fails(self, routed) -> None:
        router, _client, call_id, factory = routed(FakeTwilioClient(fail_messages=True))
        result = await router.finish_call(call_id, "CA_route", COLD)

        assert not result.succeeded
        assert result.outcome is Outcome.CALLBACK_BOOKED
        session = factory()
        try:
            callback = session.query(Callback).one()
            assert callback.sms_sid is None
        finally:
            session.close()

    async def test_no_open_slot_is_reported_not_crashed(self, routed) -> None:
        router, client, call_id, factory = routed(seed_slots=False)
        result = await router.finish_call(call_id, "CA_route", COLD)
        assert result.error == "no open slot"
        assert result.outcome is Outcome.ABANDONED
        assert result.slot_start is None
        assert client.messages_sent == []
        with factory() as session:
            assert session.query(Callback).count() == 0
            assert session.query(Lead).count() == 1

    async def test_a_caller_who_gave_no_number_gets_no_text(self, routed) -> None:
        router, client, call_id, factory = routed()
        fields = LeadFields(treatment_interest=TreatmentInterest.SINGLE_IMPLANT)
        result = await router.finish_call(call_id, "CA_route", fields)
        assert result.error == "no callback number captured"
        assert result.outcome is Outcome.ABANDONED
        assert result.slot_start is None
        assert client.messages_sent == []
        with factory() as session:
            assert session.query(Callback).count() == 0
            assert session.query(Slot).filter(Slot.booked.is_(True)).count() == 0
            assert session.query(Lead).count() == 1

    async def test_no_coordinator_routes_a_hot_lead_to_a_callback(self, routed) -> None:
        router, client, call_id, _factory = routed(coordinator_available=False)
        result = await router.finish_call(call_id, "CA_route", HOT)
        assert result.score.score == 75
        assert result.outcome is Outcome.CALLBACK_BOOKED
        assert client.call_updates == []
        assert len(client.messages_sent) == 1

    @pytest.mark.parametrize("fields", [HOT, COLD])
    async def test_database_failure_prevents_external_actions(self, routed, fields) -> None:
        router, client, call_id, factory = routed()
        with factory() as session:
            Lead.__table__.drop(session.get_bind())

        result = await router.finish_call(call_id, "CA_route", fields)

        assert result.outcome is Outcome.ABANDONED
        assert result.error == "routing persistence failed"
        assert result.lead_id is None
        assert not result.succeeded
        assert client.messages_sent == []
        assert client.call_updates == []
        with factory() as session:
            assert session.query(Callback).count() == 0
            assert session.query(Slot).filter(Slot.booked.is_(True)).count() == 0

    async def test_sms_receipt_write_failure_preserves_booking_and_sent_receipt(self, routed):
        from sqlalchemy import event
        from sqlalchemy.exc import OperationalError

        router, client, call_id, factory = routed()
        with factory() as session:
            engine = session.get_bind()

        def fail_receipt_write(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("UPDATE callbacks"):
                raise OperationalError(statement, parameters, Exception("storage unavailable"))

        event.listen(engine, "before_cursor_execute", fail_receipt_write)
        try:
            result = await router.finish_call(call_id, "CA_route", COLD, consent_turn_index=7)
        finally:
            event.remove(engine, "before_cursor_execute", fail_receipt_write)

        assert result.outcome is Outcome.CALLBACK_BOOKED
        assert result.slot_start is not None
        assert result.sms_sid == "SM_test_sid"
        assert result.error == "SMS sent but receipt persistence failed"
        assert not result.succeeded
        assert len(client.messages_sent) == 1
        with factory() as session:
            assert session.query(Callback).one().sms_sid is None
            assert session.query(Slot).filter(Slot.booked.is_(True)).count() == 1

    async def test_two_callbacks_take_different_slots(self, routed) -> None:
        router, _client, call_id, factory = routed()
        first = await router.finish_call(call_id, "CA_route", COLD)

        session = factory()
        try:
            second_call = CallRepository(session).start_call("CA_route_2", CALLER)
            second_id = second_call.id
            session.commit()
        finally:
            session.close()

        second = await router.finish_call(second_id, "CA_route_2", COLD)
        assert first.slot_start != second.slot_start


class TestSlotSeeding:
    def test_weekend_slots_are_not_created(self) -> None:
        from scripts.seed_slots import slot_times

        friday = datetime(2026, 9, 11, 8, 0, tzinfo=UTC)
        times = slot_times(friday, weeks=1)
        assert all(t.weekday() < 5 for t in times)

    def test_slots_are_business_hours_only(self) -> None:
        from scripts.seed_slots import slot_times

        times = slot_times(datetime(2026, 9, 7, 0, 0, tzinfo=UTC), weeks=1)
        assert {t.hour for t in times} == set(range(9, 17))

    def test_no_slot_is_created_in_the_past(self) -> None:
        from scripts.seed_slots import slot_times

        now = datetime(2026, 9, 8, 13, 30, tzinfo=UTC)
        assert all(t > now for t in slot_times(now, weeks=1))


class TestAvailabilityEndpoint:
    """The flag the owner flips from a phone before a test call."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        from arcagent.telephony.availability import reset_availability

        reset_availability()
        yield
        reset_availability()

    def test_it_defaults_to_the_configured_value(self) -> None:
        from fastapi.testclient import TestClient

        from arcagent.app import app
        from arcagent.config import get_settings

        app.dependency_overrides[get_settings] = lambda: settings(
            coordinator_available=False, admin_api_token="test-admin-token"
        )
        try:
            with TestClient(app, headers={"Authorization": "Bearer test-admin-token"}) as client:
                assert client.get("/admin/coordinator").json() == {"available": False}
        finally:
            app.dependency_overrides.clear()

    def test_it_can_be_flipped_and_stays_flipped(self) -> None:
        from fastapi.testclient import TestClient

        from arcagent.app import app
        from arcagent.config import get_settings

        app.dependency_overrides[get_settings] = lambda: settings(
            admin_api_token="test-admin-token"
        )
        try:
            with TestClient(app, headers={"Authorization": "Bearer test-admin-token"}) as client:
                assert client.post("/admin/coordinator?available=false").json() == {
                    "available": False
                }
                assert client.get("/admin/coordinator").json() == {"available": False}
                assert client.post("/admin/coordinator?available=true").json() == {
                    "available": True
                }
        finally:
            app.dependency_overrides.clear()


async def test_repeated_transfer_dispatch_never_redials(routed):
    from sqlalchemy import select

    from arcagent.persistence.models import Call
    from arcagent.persistence.transfer_models import TransferAttempt

    router, client, call_id, factory = routed()
    first = await router.finish_call(call_id, "CA_route", HOT)
    second = await router.finish_call(call_id, "CA_route", HOT)
    assert first.outcome is second.outcome is None
    assert len(client.call_updates) == 1
    with factory() as db:
        assert db.scalar(select(TransferAttempt)).request_status == "accepted"
        assert db.get(Call, call_id).outcome is None
        CallRepository(db).end_call(call_id, Outcome.ABANDONED)
        assert db.get(Call, call_id).outcome is None
        assert db.get(Call, call_id).ended_at is None


async def test_uncertain_request_is_queued_for_review_not_retried(routed):
    from sqlalchemy import select

    from arcagent.persistence.transfer_models import TransferAttempt
    from arcagent.persistence.workflow_models import FollowupTask

    router, client, call_id, factory = routed(FakeTwilioClient(fail_calls=True))
    await router.finish_call(call_id, "CA_route", HOT)
    await router.finish_call(call_id, "CA_route", HOT)
    with factory() as db:
        assert db.scalar(select(TransferAttempt)).request_status == "uncertain"
        assert len(list(db.scalars(select(FollowupTask)))) == 1
    assert client.messages_sent == []


async def test_invalid_callback_origin_prevents_vendor_request(routed):
    from sqlalchemy import select

    from arcagent.persistence.transfer_models import TransferAttempt

    router, client, call_id, factory = routed(public_url="http://insecure.example.test")
    result = await router.finish_call(call_id, "CA_route", HOT)
    assert result.outcome is Outcome.ABANDONED
    assert client.call_updates == []
    with factory() as db:
        assert db.scalar(select(TransferAttempt)).request_status == "failed"


def test_explicit_vendor_rejection_differs_from_transport_uncertainty():
    from twilio.base.exceptions import TwilioRestException

    class Rejected(FakeTwilioClient):
        def calls(self, sid):
            raise TwilioRestException(400, "/test", msg="sensitive vendor response")

    with pytest.raises(TransferFailed) as caught:
        TwilioActions(settings(), Rejected()).warm_transfer("CA_live", attempt_id=ATTEMPT)
    assert not caught.value.uncertain
    assert "sensitive" not in str(caught.value)


def test_transport_timeout_is_uncertain_without_sensitive_error():
    class TimedOut(FakeTwilioClient):
        def calls(self, sid):
            raise TimeoutError("sensitive vendor response")

    with pytest.raises(TransferFailed) as caught:
        TwilioActions(settings(), TimedOut()).warm_transfer("CA_live", attempt_id=ATTEMPT)
    assert caught.value.uncertain
    assert "sensitive" not in str(caught.value)
