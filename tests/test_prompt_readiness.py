"""Readiness uses effective cached prompt content and never exposes files or prompt text."""

import pytest

from arcagent.agent.readiness import PromptReadinessError, inspect_prompts, require_ready_prompts


def test_repository_placeholders_are_not_ready_for_calls():
    issues = inspect_prompts("v1")
    assert len(issues) == 7
    assert {issue.reason for issue in issues} == {"placeholder"}
    with pytest.raises(PromptReadinessError):
        require_ready_prompts("v1")


@pytest.mark.parametrize("version", ["../private-secret", "v1/../../secret", "v1\n", "V1", ""])
def test_invalid_versions_are_rejected_before_filesystem_access(version):
    issues = inspect_prompts(version)
    assert [(issue.name, issue.reason) for issue in issues] == [("version", "invalid_version")]
    with pytest.raises(PromptReadinessError) as error:
        require_ready_prompts(version)
    assert version not in str(error.value) if version else True


def test_missing_empty_and_lowercase_placeholders_are_reported_together(tmp_path, monkeypatch):
    from arcagent.agent import prompts
    from arcagent.agent.readiness import REQUIRED_PROMPTS

    root = tmp_path / "v2"
    root.mkdir()
    for name in REQUIRED_PROMPTS:
        (root / f"{name}.md").write_text("Ready fixture text")
    (root / "system.md").unlink()
    (root / "greeting.md").write_text(" \n")
    (root / "capture_contact.md").write_text("todo_owner: private patient text")
    monkeypatch.setattr(prompts, "PROMPTS_ROOT", tmp_path)
    prompts.load_prompt.cache_clear()
    try:
        issues = inspect_prompts("v2")
        assert {(issue.name, issue.reason) for issue in issues} == {
            ("system", "missing"),
            ("greeting", "empty"),
            ("capture_contact", "placeholder"),
        }
        with pytest.raises(PromptReadinessError) as error:
            require_ready_prompts("v2")
        assert "private patient text" not in str(error.value)
        assert str(tmp_path) not in str(error.value)
    finally:
        prompts.load_prompt.cache_clear()


def test_authenticated_voice_refuses_placeholder_prompts_before_vendor_work(monkeypatch):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from twilio.request_validator import RequestValidator

    from arcagent.app import app
    from arcagent.config import Settings, get_settings

    settings = Settings(
        _env_file=None,
        env="test",
        public_url="https://voice.example",
        twilio_auth_token="fixture",
        enable_audio_evals=True,
        audio_eval_token="eval-fixture",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    opened = []

    async def forbidden(self):
        opened.append(True)
        raise AssertionError("not-ready voice must not start vendors")

    monkeypatch.setattr("arcagent.speech.deepgram_stt.DeepgramSTT.start", forbidden)
    try:
        with TestClient(app) as client:
            signed = {
                "X-Twilio-Signature": RequestValidator("fixture").compute_signature(
                    "https://voice.example/voice/inbound", {}
                )
            }
            response = client.post("/voice/inbound", headers=signed)
            assert response.status_code == 503
            assert response.json() == {"detail": "voice service is not ready"}
            assert client.post("/voice/inbound").status_code == 403
            for path, headers in [
                (
                    "/voice/stream",
                    {
                        "X-Twilio-Signature": RequestValidator("fixture").compute_signature(
                            "wss://voice.example/voice/stream", {}
                        )
                    },
                ),
                ("/eval/voice/stream", {"Authorization": "Bearer eval-fixture"}),
            ]:
                with pytest.raises(WebSocketDisconnect) as error:
                    with client.websocket_connect(path, headers=headers):
                        pass
                assert error.value.code == 1011
                assert error.value.reason == "voice service is not ready"
                with pytest.raises(WebSocketDisconnect) as unauth:
                    with client.websocket_connect(path):
                        pass
                assert unauth.value.code == 1008
        assert opened == []
    finally:
        app.dependency_overrides.clear()


def test_valid_bundle_passes_and_uses_cached_effective_content(ready_prompts):
    from arcagent.agent import prompts

    require_ready_prompts("v1")
    assert inspect_prompts("v1") == []
    # The running graph still sees its cached good string after a disk edit.
    (prompts.PROMPTS_ROOT / "v1" / "system.md").write_text("TODO_OWNER: changed on disk")
    require_ready_prompts("v1")
    prompts.load_prompt.cache_clear()
    assert [(issue.name, issue.reason) for issue in inspect_prompts("v1")] == [
        ("system", "placeholder")
    ]


def test_unreadable_prompt_reports_code_without_bytes_or_path(ready_prompts):
    from arcagent.agent import prompts

    (prompts.PROMPTS_ROOT / "v1" / "system.md").write_bytes(b"\xff\xfeprivate-secret")
    prompts.load_prompt.cache_clear()
    issues = inspect_prompts("v1")
    assert [(issue.name, issue.reason) for issue in issues] == [("system", "unreadable")]
