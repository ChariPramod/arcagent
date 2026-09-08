"""Objection detection.

A keyword pass runs first and a model call only runs when the keywords are ambiguous. The
keyword pass costs nothing and catches the blunt cases ("how much does this cost"), which
matters on a latency budget where every avoided model call is 200 to 400 ms back.

Detection never decides anything the score depends on by itself. It routes the conversation
into ``handle_objection``; whether the objection was *recovered* is the handling node's
structured output, and that is the field scoring rule 8 reads.
"""

from __future__ import annotations

import re

from arcagent.agent.state import ObjectionKind

# Phrases that are an objection on their own, with no model call needed. Ordered by how
# specific they are: "just looking" beats a bare price question when both appear.
KEYWORD_PATTERNS: tuple[tuple[ObjectionKind, re.Pattern[str]], ...] = (
    (
        ObjectionKind.JUST_LOOKING,
        re.compile(
            r"\b(just (looking|browsing|curious|checking|getting info(rmation)?)"
            r"|only want(ed)? (some )?info(rmation)?"
            r"|not ready|no rush|shopping around)\b",
            re.I,
        ),
    ),
    (
        ObjectionKind.SPOUSE,
        re.compile(
            r"\b(my (husband|wife|spouse|partner)|talk (to|with) my|check with my"
            r"|discuss (it|this) with)\b",
            re.I,
        ),
    ),
    (
        ObjectionKind.BAD_EXPERIENCE,
        re.compile(
            r"\b(bad experience|last dentist|previous dentist|another dentist"
            r"|messed (it )?up|botched|went wrong)\b",
            re.I,
        ),
    ),
    (
        ObjectionKind.FEAR,
        re.compile(
            r"\b(scared|afraid|nervous|terrified|anxious|hate the dentist"
            r"|(worried|worry) about the (surgery|pain|procedure)|put me (to sleep|under))\b",
            re.I,
        ),
    ),
    (
        ObjectionKind.PRICE,
        # The currency branch sits outside the \b group on purpose: there is no word
        # boundary before a "$", so "$30,000" would never match inside one.
        re.compile(
            r"(?:\b(?:how much|what.s the (?:cost|price)|too expensive"
            r"|(?:can'?t|cannot|can not) afford"
            r"|out of my (?:price )?range|cost too much|thousand)\b"
            r"|\$\s?\d)",
            re.I,
        ),
    ),
)


def detect_keywords(text: str) -> ObjectionKind | None:
    """First pass. Returns the most specific objection the text plainly contains."""
    if not text:
        return None
    for kind, pattern in KEYWORD_PATTERNS:
        if pattern.search(text):
            return kind
    return None


# A caller can raise the same objection twice. The second time is not a new objection
# unless the first was marked recovered, otherwise the graph would loop on it.
def should_enter_handler(
    detected: ObjectionKind | None,
    already_open: bool,
) -> bool:
    """Whether the graph should divert into ``handle_objection``."""
    return detected is not None and not already_open
