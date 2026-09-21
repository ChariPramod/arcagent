"""Audio quality is assessed against persona expectations, not connection completion."""

from evals.audio_scoring import assess_audio
from evals.persona import Expected


def test_matching_completed_audio_passes_with_existing_normalization():
    result = assess_audio(
        Expected(
            outcome="callback_booked", fields={"name": "Sam Lee", "callback_number": "4155550123"}
        ),
        {"name": " sam  LEE ", "callback_number": "+1 (415) 555-0123"},
        "callback_booked",
        None,
        1,
    )
    assert result.passed
    assert result.outcome_correct and result.handoff_correct
    assert result.field_accuracy == 1.0
    assert result.missed_fields == ()
    assert result.reasons == ()


def test_wrong_outcome_and_false_handoff_fail_even_when_audio_completes():
    result = assess_audio(Expected(outcome="callback_booked"), {}, "handoff", None, 1)
    assert not result.passed
    assert not result.outcome_correct
    assert not result.handoff_correct
    assert result.reasons == ("outcome_mismatch", "handoff_mismatch")


def test_wrong_fields_fail_with_only_field_names_in_diagnostics():
    result = assess_audio(
        Expected(
            outcome="handoff", handoff=True, fields={"name": "Expected Person", "pain_level": 8}
        ),
        {"name": "Private Person", "pain_level": 8},
        "handoff",
        None,
        2,
    )
    assert not result.passed
    assert result.field_accuracy == 0.5
    assert result.missed_fields == ("name",)
    assert result.reasons == ("field_mismatch",)
    assert "Private Person" not in repr(result)


def test_unspoken_fields_are_excluded_without_penalizing_pass():
    result = assess_audio(
        Expected(
            outcome="callback_booked",
            fields={"name": "Unspoken", "pain_level": 0},
            not_expected=["name"],
        ),
        {"pain_level": 0},
        "callback_booked",
        None,
        1,
    )
    assert result.passed
    assert result.field_accuracy == 1.0
    assert result.missed_fields == ()


def test_missing_snapshot_fails_even_when_no_fields_are_expected():
    result = assess_audio(Expected(outcome="wrong_number"), None, "wrong_number", None, 1)
    assert not result.passed
    assert result.field_accuracy is None
    assert result.missed_fields == ()
    assert result.reasons == ("missing_snapshot",)


def test_transport_error_fails_without_copying_sensitive_error_text():
    result = assess_audio(
        Expected(outcome="wrong_number"), {}, "wrong_number", "token=secret patient-name", 1
    )
    assert not result.passed
    assert result.reasons == ("transport_error",)
    assert "secret" not in repr(result)


def test_no_caller_turns_cannot_pass():
    result = assess_audio(Expected(outcome="wrong_number"), {}, "wrong_number", None, 0)
    assert not result.passed
    assert result.reasons == ("no_caller_turns",)


def test_outcome_matching_uses_shared_case_and_whitespace_normalization():
    result = assess_audio(Expected(outcome="wrong_number"), {}, "  WRONG_NUMBER  ", None, 1)
    assert result.passed


def test_handoff_expectation_is_checked_independently_of_outcome_string():
    result = assess_audio(Expected(outcome="handoff", handoff=False), {}, "handoff", None, 1)
    assert result.outcome_correct
    assert not result.handoff_correct
    assert not result.passed
    assert result.reasons == ("handoff_mismatch",)


def test_multiple_failures_are_retained_as_fixed_reason_codes():
    result = assess_audio(
        Expected(outcome="handoff", handoff=True, fields={"pain_level": 8}),
        None,
        None,
        "sensitive failure",
        0,
    )
    assert not result.passed
    assert result.field_accuracy is None
    assert result.missed_fields == ("pain_level",)
    assert result.reasons == (
        "transport_error",
        "no_caller_turns",
        "missing_snapshot",
        "outcome_mismatch",
        "handoff_mismatch",
        "field_mismatch",
    )
