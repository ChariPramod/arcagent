"""PII never reaches a log sink in the clear."""

from __future__ import annotations

from arcagent.logging import (
    hash_number,
    mask_name,
    mask_number,
    redact_processor,
    redact_text,
)


def test_phone_numbers_are_scrubbed_from_free_text() -> None:
    for raw in ["+14155550123", "(415) 555-0123", "415-555-0123", "4155550123"]:
        out = redact_text(f"call me at {raw} tomorrow")
        assert raw not in out
        assert "[phone]" in out


def test_emails_are_scrubbed_from_free_text() -> None:
    out = redact_text("reach me at jane.doe+dental@example.com")
    assert "jane.doe+dental@example.com" not in out
    assert "[email]" in out


def test_name_keys_are_masked() -> None:
    assert mask_name("Maria Gonzalez") == "M. G."
    event = redact_processor(None, "info", {"event": "lead", "name": "Maria Gonzalez"})
    assert event["name"] == "M. G."
    assert "Maria" not in str(event)


def test_number_keys_are_masked() -> None:
    assert mask_number("+14155550123") == "***0123"
    event = redact_processor(None, "info", {"callback_number": "+14155550123"})
    assert event["callback_number"] == "***0123"


def test_transcript_text_is_never_emitted() -> None:
    event = redact_processor(None, "info", {"event": "turn", "text": "I need a full arch"})
    assert "full arch" not in str(event)
    assert event["text"] == "<18 chars redacted>"


def test_nested_structures_are_redacted() -> None:
    event = redact_processor(
        None,
        "info",
        {"lead": {"name": "Bob Smith", "notes": ["ring 415-555-0123"]}},
    )
    assert event["lead"]["name"] == "B. S."
    assert "415-555-0123" not in str(event)


def test_hash_number_is_stable_and_not_reversible() -> None:
    h = hash_number("+14155550123")
    assert h == hash_number("+14155550123")
    assert h != hash_number("+14155550124")
    assert "4155550123" not in h
    assert len(h) == 16
