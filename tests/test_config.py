"""Settings load from the environment and never carry baked in credentials."""

from __future__ import annotations

import pytest

from arcagent.config import Settings


def test_defaults_have_no_credentials() -> None:
    s = Settings(_env_file=None)
    assert s.twilio_account_sid == ""
    assert s.deepgram_api_key == ""
    assert s.cartesia_api_key == ""
    assert s.llm_api_key == ""


def test_values_come_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("HANDOFF_THRESHOLD", "72")
    s = Settings(_env_file=None)
    assert s.twilio_account_sid == "AC_test"
    assert s.handoff_threshold == 72


@pytest.mark.parametrize(
    ("public_url", "expected"),
    [
        ("https://example.ngrok.app", "wss://example.ngrok.app/voice/stream"),
        ("http://example.ngrok.app/", "wss://example.ngrok.app/voice/stream"),
        ("example.ngrok.app", "wss://example.ngrok.app/voice/stream"),
    ],
)
def test_stream_url_is_derived_from_public_url(public_url: str, expected: str) -> None:
    assert Settings(_env_file=None, public_url=public_url).stream_url == expected
