"""The inbound webhook returns a stream TwiML document and rejects unsigned requests."""

from __future__ import annotations

import base64
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from arcagent.app import app
from arcagent.config import Settings, get_settings
from arcagent.telephony.twiml import connect_stream, dial_coordinator
from tests.fakes import connected_message, media_message, start_message, stop_message

AUTH_TOKEN = "test_auth_token_not_a_real_credential"
PUBLIC_URL = "https://arcagent.example.ngrok.app"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """App wired to a known PUBLIC_URL and auth token, with signature validation on."""
    settings = Settings(
        _env_file=None,
        public_url=PUBLIC_URL,
        twilio_auth_token=AUTH_TOKEN,
        validate_twilio_signature=True,
        coordinator_number="+15550001111",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _signed_headers(url: str, params: dict[str, str]) -> dict[str, str]:
    signature = RequestValidator(AUTH_TOKEN).compute_signature(url, params)
    return {"X-Twilio-Signature": signature}


class TestTwiml:
    def test_connect_stream_document(self) -> None:
        xml = connect_stream("wss://example.test/voice/stream")
        assert "<Connect>" in xml
        assert '<Stream url="wss://example.test/voice/stream" />' in xml

    def test_dial_coordinator_document(self) -> None:
        xml = dial_coordinator("+15550001111")
        assert "<Dial>+15550001111</Dial>" in xml


class TestInboundWebhook:
    def test_signed_request_gets_stream_twiml(self, client: TestClient) -> None:
        url = f"{PUBLIC_URL}/voice/inbound"
        params = {"CallSid": "CA_test", "From": "+15551234567"}
        response = client.post("/voice/inbound", data=params, headers=_signed_headers(url, params))
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/xml")
        assert "wss://arcagent.example.ngrok.app/voice/stream" in response.text

    def test_unsigned_request_is_rejected(self, client: TestClient) -> None:
        response = client.post("/voice/inbound", data={"CallSid": "CA_test"})
        assert response.status_code == 403

    def test_signature_over_a_different_body_is_rejected(self, client: TestClient) -> None:
        url = f"{PUBLIC_URL}/voice/inbound"
        headers = _signed_headers(url, {"CallSid": "CA_test"})
        response = client.post("/voice/inbound", data={"CallSid": "CA_tampered"}, headers=headers)
        assert response.status_code == 403

    def test_missing_auth_token_fails_closed(self) -> None:
        """Validation on with no token configured must refuse, not wave the request through."""
        settings = Settings(_env_file=None, public_url=PUBLIC_URL, validate_twilio_signature=True)
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            with TestClient(app, raise_server_exceptions=False) as test_client:
                response = test_client.post("/voice/inbound", data={})
            assert response.status_code == 500
        finally:
            app.dependency_overrides.clear()

    def test_validation_can_be_disabled_for_local_development(self) -> None:
        settings = Settings(_env_file=None, public_url=PUBLIC_URL, validate_twilio_signature=False)
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            with TestClient(app) as test_client:
                response = test_client.post("/voice/inbound", data={"CallSid": "CA_test"})
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()


class TestStreamRoute:
    """The real ASGI WebSocket route, not the fake socket."""

    def test_media_frames_are_echoed_over_the_real_route(self, client: TestClient) -> None:
        payload = bytes([0xFF, 0x7E]) * 80
        with client.websocket_connect("/voice/stream") as ws:
            ws.send_json(connected_message())
            ws.send_json(start_message())
            ws.send_json(media_message(payload))
            echoed = ws.receive_json()
            ws.send_json(stop_message())
        assert echoed["event"] == "media"
        assert base64.b64decode(echoed["media"]["payload"]) == payload

    def test_client_hangup_closes_the_session_cleanly(self, client: TestClient) -> None:
        with client.websocket_connect("/voice/stream") as ws:
            ws.send_json(start_message())
            ws.close()
