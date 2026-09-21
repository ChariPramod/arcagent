"""Public voice boundaries reject untrusted callers before opening vendor streams."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from twilio.request_validator import RequestValidator

from arcagent.app import app
from arcagent.config import Settings, get_settings

TOKEN = "test-only-twilio-token"
PUBLIC_URL = "https://voice.example.test"


@pytest.fixture
def settings():
    value = Settings(_env_file=None, public_url=PUBLIC_URL, twilio_auth_token=TOKEN)
    app.dependency_overrides[get_settings] = lambda: value
    yield value
    app.dependency_overrides.clear()


def signed(path):
    return {
        "X-Twilio-Signature": RequestValidator(TOKEN).compute_signature(
            PUBLIC_URL.replace("https://", "wss://") + path, {}
        )
    }


def test_unsigned_stream_rejected_before_vendor_work(settings, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("unsigned connection opened a paid vendor stream")

    monkeypatch.setattr("arcagent.speech.deepgram_stt.DeepgramSTT.start", forbidden)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/voice/stream"):
                pass
    assert error.value.code == 1008


def test_echo_is_disabled_by_default_even_with_a_signature(settings):
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/voice/echo", headers=signed("/voice/echo")):
                pass
    assert error.value.code == 1008


@pytest.mark.parametrize("method", ["get", "post"])
def test_coordinator_admin_fails_closed_without_configured_token(settings, method):
    with TestClient(app) as client:
        response = getattr(client, method)("/admin/coordinator?available=false")
    assert response.status_code == 503


@pytest.mark.parametrize("credentials", [None, "Bearer wrong", "Bearer read-only", "Basic admin"])
def test_admin_rejects_missing_or_wrong_capabilities(settings, credentials):
    settings.admin_api_token = "admin"
    settings.console_api_token = "read-only"
    headers = {"Authorization": credentials} if credentials else {}
    with TestClient(app) as client:
        response = client.post("/admin/coordinator?available=false", headers=headers)
        assert response.status_code == 401
        assert (
            client.get("/admin/coordinator", headers={"Authorization": "Bearer admin"}).status_code
            == 200
        )


def test_production_cannot_disable_webhook_validation(settings):
    settings.env = "prod"
    settings.validate_twilio_signature = False
    with TestClient(app) as client:
        assert client.post("/voice/inbound").status_code == 403


@pytest.mark.parametrize("failure", ["stt", "tts"])
def test_startup_failure_closes_both_vendor_adapters(settings, monkeypatch, failure, ready_prompts):
    closed = set()

    async def start_stt(self):
        if failure == "stt":
            raise RuntimeError("simulated STT outage")

    async def start_tts(self):
        raise RuntimeError("simulated TTS outage")

    async def close_stt(self):
        closed.add("stt")

    async def close_tts(self):
        closed.add("tts")

    monkeypatch.setattr("arcagent.speech.deepgram_stt.DeepgramSTT.start", start_stt)
    monkeypatch.setattr("arcagent.speech.cartesia_tts.CartesiaTTS.start", start_tts)
    monkeypatch.setattr("arcagent.speech.deepgram_stt.DeepgramSTT.close", close_stt)
    monkeypatch.setattr("arcagent.speech.cartesia_tts.CartesiaTTS.close", close_tts)
    with TestClient(app) as client:
        with pytest.raises(RuntimeError, match="simulated"):
            with client.websocket_connect("/voice/stream", headers=signed("/voice/stream")) as ws:
                ws.receive_json()
    assert closed == {"stt", "tts"}


@pytest.mark.parametrize("path", ["/voice/stream", "/voice/echo"])
@pytest.mark.parametrize("signature_path", ["/other", "/voice/stream?changed=true"])
def test_signature_for_another_url_cannot_open_voice(settings, path, signature_path):
    settings.echo_enabled = True
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(path, headers=signed(signature_path)):
                pass
    assert error.value.code == 1008


def test_enabled_echo_accepts_signed_public_url_with_query_behind_proxy(settings):
    settings.echo_enabled = True
    path = "/voice/echo?session=opaque%2Fvalue"
    with TestClient(app) as client:
        with client.websocket_connect(path, headers=signed(path)) as ws:
            ws.close()


def test_enabled_echo_accepts_documented_trailing_slash_signature(settings):
    settings.echo_enabled = True
    with TestClient(app) as client:
        with client.websocket_connect("/voice/echo", headers=signed("/voice/echo/")) as ws:
            ws.close()


@pytest.mark.parametrize("missing_token", [False, True])
def test_production_stream_cannot_bypass_signature_validation(settings, missing_token):
    settings.env = "prod"
    settings.validate_twilio_signature = False
    if missing_token:
        settings.twilio_auth_token = ""
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/voice/stream"):
                pass
    assert error.value.code == 1008


def test_eval_route_is_disabled_by_default(settings):
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/eval/voice/stream"):
                pass
    assert error.value.code == 1008


@pytest.mark.parametrize(
    ("environment", "enabled", "token", "header"),
    [
        ("prod", True, "eval-secret", "Bearer eval-secret"),
        ("dev", True, "eval-secret", "Bearer eval-secret"),
        ("test", False, "eval-secret", "Bearer eval-secret"),
        ("test", True, "", "Bearer "),
        ("test", True, "eval-secret", "Bearer wrong"),
        ("test", True, "eval-secret", "Basic eval-secret"),
        ("test", True, "eval-secret", ""),
    ],
)
def test_eval_route_fails_closed_before_vendor_work(
    settings, monkeypatch, environment, enabled, token, header
):
    settings.env = environment
    settings.enable_audio_evals = enabled
    settings.audio_eval_token = token

    async def forbidden(*args, **kwargs):
        raise AssertionError("unauthorized evaluation opened a vendor connection")

    monkeypatch.setattr("arcagent.speech.deepgram_stt.DeepgramSTT.start", forbidden)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/eval/voice/stream", headers={"Authorization": header}):
                pass
    assert error.value.code == 1008


def test_authorized_eval_reaches_pipeline_without_twilio_signature(
    settings, monkeypatch, ready_prompts
):
    settings.env = "test"
    settings.enable_audio_evals = True
    settings.audio_eval_token = "eval-secret"

    async def offline(*args, **kwargs):
        raise RuntimeError("offline vendor reached")

    monkeypatch.setattr("arcagent.speech.deepgram_stt.DeepgramSTT.start", offline)
    with TestClient(app) as client:
        with pytest.raises(RuntimeError, match="offline vendor reached"):
            with client.websocket_connect(
                "/eval/voice/stream", headers={"Authorization": "Bearer eval-secret"}
            ) as ws:
                ws.receive_json()
