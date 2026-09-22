"""Real signature and database boundary for transfer evidence; no vendor calls."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from twilio.request_validator import RequestValidator

from arcagent.app import app
from arcagent.config import Settings, get_settings
from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import Base, Call, Outcome
from arcagent.persistence.repo import CallRepository
from arcagent.persistence.transfer_models import TransferAttempt
from arcagent.persistence.workflow_models import FollowupTask
from arcagent.telephony.transfer_state import begin_transfer


@pytest.fixture
def transfer_client(tmp_path):
    url = f"sqlite:///{tmp_path / 'transfer.db'}"
    Base.metadata.create_all(get_engine(url))
    config = Settings(
        _env_file=None,
        database_url=url,
        public_url="https://voice.example.test",
        twilio_account_sid="AC_test",
        twilio_auth_token="test-secret",
        env="prod",
    )
    with session_scope(url) as db:
        call = CallRepository(db).start_call("CA_parent", "")
        attempt, _ = begin_transfer(db, call.id)
        identifier, call_id = attempt.id, call.id
    app.dependency_overrides[get_settings] = lambda: config
    with TestClient(app) as client:

        def send(kind="action", *, signed=True, **overrides):
            path = f"/voice/transfer/{identifier}/{kind}"
            body = {
                "AccountSid": "AC_test",
                "CallSid": "CA_parent",
                "DialCallSid": "CA_child",
                "DialCallStatus": "completed",
                "DialBridged": "true",
            }
            if kind == "progress":
                body = {
                    "AccountSid": "AC_test",
                    "CallSid": "CA_child",
                    "ParentCallSid": "CA_parent",
                    "CallStatus": "completed",
                    "SequenceNumber": "2",
                }
            body.update(overrides)
            signature = RequestValidator(config.twilio_auth_token).compute_signature(
                config.public_url + path, body
            )
            return client.post(
                path, data=body, headers={"X-Twilio-Signature": signature if signed else "wrong"}
            )

        yield send, url, identifier, call_id
    app.dependency_overrides.clear()


def test_progress_completion_is_not_bridge_confirmation(transfer_client):
    send, url, _, call_id = transfer_client
    assert send("progress").status_code == 204
    with session_scope(url) as db:
        assert db.get(Call, call_id).outcome is None
    response = send()
    assert response.status_code == 200
    assert "<Hangup" in response.text
    with session_scope(url) as db:
        assert db.get(Call, call_id).outcome is Outcome.HANDOFF
        CallRepository(db).end_call(call_id, Outcome.ABANDONED)
        assert db.get(Call, call_id).outcome is Outcome.HANDOFF


@pytest.mark.parametrize(
    "overrides", [{"AccountSid": "AC_other"}, {"CallSid": "CA_other"}, {"DialCallSid": "CA_parent"}]
)
def test_mismatched_evidence_cannot_finalize(transfer_client, overrides):
    send, url, _, call_id = transfer_client
    assert send(**overrides).status_code in {400, 403}
    with session_scope(url) as db:
        assert db.get(Call, call_id).outcome is None


def test_invalid_signature_is_rejected(transfer_client):
    send, _, _, _ = transfer_client
    assert send(signed=False).status_code == 403


@pytest.mark.parametrize("status", ["busy", "no-answer", "failed", "canceled"])
def test_failure_recovery_is_durable_and_repeatable(transfer_client, status):
    send, url, _, call_id = transfer_client
    first = send(DialCallStatus=status, DialBridged="false")
    again = send(DialCallStatus=status, DialBridged="false")
    assert first.status_code == again.status_code == 200
    assert first.text == again.text
    assert "<Say" in first.text and "<Hangup" in first.text
    with session_scope(url) as db:
        assert db.get(Call, call_id).outcome is Outcome.ABANDONED
        assert len(list(db.scalars(select(FollowupTask)))) == 1


def test_db_failure_is_not_acknowledged(transfer_client):
    send, url, _, _ = transfer_client
    TransferAttempt.__table__.drop(get_engine(url))
    assert send().status_code == 503


def test_child_binding_and_out_of_order_progress(transfer_client):
    send, _, _, _ = transfer_client
    assert send("progress", CallStatus="ringing", SequenceNumber="1").status_code == 204
    assert send("progress", CallStatus="initiated", SequenceNumber="0").status_code == 204
    assert send("progress", CallStatus="ringing", SequenceNumber="1").status_code == 204
    assert send("progress", CallStatus="in-progress", SequenceNumber="1").status_code == 400
    assert send(DialCallSid="CA_other").status_code == 400
    assert send().status_code == 200


def test_unbridged_completion_never_claims_handoff(transfer_client):
    send, url, _, call_id = transfer_client
    response = send(DialBridged="false")
    assert response.status_code == 200
    assert "<Say" in response.text
    with session_scope(url) as db:
        assert db.get(Call, call_id).outcome is Outcome.ABANDONED


def test_unsigned_progress_cannot_bind_child(transfer_client):
    send, url, identifier, _ = transfer_client
    assert send("progress", signed=False, CallSid="CA_attacker").status_code == 403
    with session_scope(url) as db:
        assert db.get(TransferAttempt, identifier).child_call_sid is None


def test_completed_action_retry_does_not_start_recovery(transfer_client):
    send, url, _, call_id = transfer_client
    first = send()
    again = send(DialCallStatus="no-answer", DialBridged="false")
    assert first.status_code == again.status_code == 200
    assert first.text == again.text
    with session_scope(url) as db:
        assert db.get(Call, call_id).outcome is Outcome.HANDOFF
        assert not list(db.scalars(select(FollowupTask)))


def test_dev_signature_bypass_cannot_admit_transfer_evidence(transfer_client):
    send, url, _, call_id = transfer_client
    config = app.dependency_overrides[get_settings]()
    app.dependency_overrides[get_settings] = lambda: config.model_copy(
        update={"env": "dev", "validate_twilio_signature": False}
    )
    assert send(signed=False).status_code == 403
    assert send().status_code == 200
    with session_scope(url) as db:
        assert db.get(Call, call_id).outcome is Outcome.HANDOFF
