"""Server provenance records effective inputs while excluding deployment secrets."""

import hashlib
import json

from arcagent.agent.prompts import load_prompt
from arcagent.config import Settings
from arcagent.telephony.eval_config import AudioServerConfig, build_eval_config


def test_server_config_records_effective_inputs_without_secrets():
    settings = Settings(
        _env_file=None,
        handoff_threshold=71,
        coordinator_available=True,
        llm_model="agent-fixture",
        llm_model_extraction="unused-extraction-fixture",
        deepgram_endpointing_ms=333,
        cartesia_voice_id="voice-fixture",
        twilio_auth_token="secret-twilio",
        llm_api_key="secret-model",
        deepgram_api_key="secret-stt",
        cartesia_api_key="secret-tts",
        audio_eval_token="secret-eval",
        admin_api_token="secret-admin",
        console_api_token="secret-console",
        database_url="secret-database",
        public_url="https://secret.example",
        twilio_number="+15551112222",
    )
    snapshot = build_eval_config(settings, coordinator_available=False)
    assert AudioServerConfig.model_validate(snapshot).model_dump() == snapshot
    assert snapshot["threshold"] == 71
    assert snapshot["coordinator_available"] is False
    assert snapshot["agent_model"] == "agent-fixture"
    assert snapshot["speech"]["deepgram"]["endpointing"] == "333"
    assert snapshot["speech"]["cartesia"]["voice_id"] == "voice-fixture"
    assert (
        snapshot["prompts"]["system"]["sha256"]
        == hashlib.sha256(load_prompt("system").encode()).hexdigest()
    )
    assert "arcagent/app.py" in snapshot["source_hashes"]
    serialized = json.dumps(snapshot)
    for forbidden in ("secret-", "secret.example", "+15551112222", "unused-extraction-fixture"):
        assert forbidden not in serialized


def test_hashes_follow_cached_prompts_and_source_contents(tmp_path, monkeypatch):
    from arcagent.agent import prompts
    from arcagent.telephony import eval_config

    prompt_dir = tmp_path / "v1"
    prompt_dir.mkdir()
    for name in eval_config.PROMPT_NAMES:
        (prompt_dir / f"{name}.md").write_text("first prompt")
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_file = source_root / "app.py"
    source_file.write_text("first source")
    monkeypatch.setattr(prompts, "PROMPTS_ROOT", tmp_path)
    monkeypatch.setattr(eval_config, "SOURCE_ROOT", source_root)
    load_prompt.cache_clear()
    try:
        first = build_eval_config(Settings(_env_file=None), True)
        (prompt_dir / "system.md").write_text("second prompt")
        source_file.write_text("second source")
        second = build_eval_config(Settings(_env_file=None), True)
        assert second["prompts"] == first["prompts"]
        assert second["source_hashes"] != first["source_hashes"]
        load_prompt.cache_clear()
        third = build_eval_config(Settings(_env_file=None), True)
        assert third["prompts"]["system"] != first["prompts"]["system"]
    finally:
        load_prompt.cache_clear()


def test_eval_config_precedes_vendor_start_and_is_absent_on_live_route(monkeypatch, ready_prompts):
    import pytest
    from fastapi.testclient import TestClient

    from arcagent.app import app
    from arcagent.config import get_settings

    settings = Settings(
        _env_file=None,
        env="test",
        enable_audio_evals=True,
        audio_eval_token="fixture",
        validate_twilio_signature=False,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    async def offline(self):
        raise RuntimeError("vendor boundary reached")

    monkeypatch.setattr("arcagent.speech.deepgram_stt.DeepgramSTT.start", offline)
    received = []
    live_received = []
    try:
        with TestClient(app) as client:
            with pytest.raises(RuntimeError, match="vendor boundary reached"):
                with client.websocket_connect(
                    "/eval/voice/stream", headers={"Authorization": "Bearer fixture"}
                ) as ws:
                    frame = ws.receive_json()
                    received.append(frame)
                    assert frame["event"] == "eval.config"
                    AudioServerConfig.model_validate(frame["config"])
                    ws.receive_json()
            assert len(received) == 1
            with pytest.raises(RuntimeError, match="vendor boundary reached"):
                with client.websocket_connect("/voice/stream") as ws:
                    live_received.append(ws.receive_json())
            assert live_received == []
    finally:
        app.dependency_overrides.clear()


def test_snapshot_failure_closes_before_vendor_start(monkeypatch, ready_prompts):
    from fastapi.testclient import TestClient

    from arcagent.app import app
    from arcagent.config import get_settings

    settings = Settings(
        _env_file=None,
        env="test",
        enable_audio_evals=True,
        audio_eval_token="fixture",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    opened = []

    async def forbidden(self):
        opened.append(True)
        raise AssertionError("snapshot failure must not open vendors")

    def unavailable_snapshot(*args, **kwargs):
        raise OSError("synthetic source snapshot failure")

    monkeypatch.setattr("arcagent.app.build_eval_config", unavailable_snapshot)
    monkeypatch.setattr("arcagent.speech.deepgram_stt.DeepgramSTT.start", forbidden)
    try:
        with TestClient(app) as client:
            with client.websocket_connect(
                "/eval/voice/stream", headers={"Authorization": "Bearer fixture"}
            ) as ws:
                message = ws.receive()
                assert message["type"] == "websocket.close"
                assert message["code"] == 1011
                assert message["reason"] == "evaluation configuration unavailable"
        assert opened == []
    finally:
        app.dependency_overrides.clear()


def test_strict_schema_rejects_extra_secret_fields_and_incomplete_hash_sets():
    import pytest
    from pydantic import ValidationError

    config = build_eval_config(Settings(_env_file=None), True)
    config["speech"]["deepgram"]["api_key"] = "secret"
    with pytest.raises(ValidationError):
        AudioServerConfig.model_validate(config)
    del config["speech"]["deepgram"]["api_key"]
    del config["prompts"]["system"]
    with pytest.raises(ValidationError):
        AudioServerConfig.model_validate(config)


def test_schema_version_must_be_an_integer_not_a_boolean():
    import pytest
    from pydantic import ValidationError

    config = build_eval_config(Settings(_env_file=None), True)
    config["schema_version"] = True
    with pytest.raises(ValidationError):
        AudioServerConfig.model_validate(config)
