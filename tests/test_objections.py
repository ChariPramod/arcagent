"""The keyword pass that runs before any model call.

The point of this pass is latency: a blunt objection should never cost a round trip. It is
allowed to miss subtle cases, so the tests assert on what it must catch and what it must
not falsely catch, not on exhaustive coverage.
"""

from __future__ import annotations

import pytest

from arcagent.agent.objections import detect_keywords, should_enter_handler
from arcagent.agent.state import ObjectionKind


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("how much does a full arch cost", ObjectionKind.PRICE),
        ("what's the price for implants", ObjectionKind.PRICE),
        ("that's too expensive for me", ObjectionKind.PRICE),
        ("i cannot afford thirty thousand dollars", ObjectionKind.PRICE),
        ("i can't afford that", ObjectionKind.PRICE),
        ("i heard it's like $30,000", ObjectionKind.PRICE),
        ("i'm scared of the surgery", ObjectionKind.FEAR),
        ("i'm really nervous about this", ObjectionKind.FEAR),
        ("will you put me to sleep", ObjectionKind.FEAR),
        ("i'm just looking for information", ObjectionKind.JUST_LOOKING),
        ("just curious really", ObjectionKind.JUST_LOOKING),
        ("i'm shopping around", ObjectionKind.JUST_LOOKING),
        ("i need to talk to my husband", ObjectionKind.SPOUSE),
        ("let me check with my wife", ObjectionKind.SPOUSE),
        ("i had a bad experience last time", ObjectionKind.BAD_EXPERIENCE),
        ("my previous dentist messed it up", ObjectionKind.BAD_EXPERIENCE),
    ],
)
def test_blunt_objections_are_caught_without_a_model_call(
    utterance: str, expected: ObjectionKind
) -> None:
    assert detect_keywords(utterance) is expected


@pytest.mark.parametrize(
    "utterance",
    [
        "i need all my upper teeth replaced",
        "it started hurting about a month ago",
        "yes i have insurance through work",
        "my name is bob and my number is the one i'm calling from",
        "tuesday afternoon works for me",
        "",
    ],
)
def test_ordinary_answers_are_not_objections(utterance: str) -> None:
    assert detect_keywords(utterance) is None


def test_the_more_specific_objection_wins_when_two_appear() -> None:
    """ "just looking" plus a price question is a browser, not a price objector."""
    assert detect_keywords("i'm just looking, how much is it") is ObjectionKind.JUST_LOOKING


def test_detection_is_case_insensitive() -> None:
    assert detect_keywords("HOW MUCH DOES THIS COST") is ObjectionKind.PRICE


class TestHandlerEntry:
    def test_a_new_objection_enters_the_handler(self) -> None:
        assert should_enter_handler(ObjectionKind.PRICE, already_open=False)

    def test_an_objection_already_being_handled_does_not_re_enter(self) -> None:
        """Otherwise a caller repeating themselves would loop the graph."""
        assert not should_enter_handler(ObjectionKind.PRICE, already_open=True)

    def test_no_objection_never_enters(self) -> None:
        assert not should_enter_handler(None, already_open=False)
        assert not should_enter_handler(None, already_open=True)
