"""Callers who should not be qualified.

Scope section 3.8. Each of these ends the call early on purpose: qualifying a caller who
reached the wrong number, is already a patient, or is a minor wastes their time and
produces a lead record that is worse than no record.

Detection is keyword only. A false positive here ends a call that should have continued,
so the patterns are deliberately narrow: they match statements, not topics.
"""

from __future__ import annotations

import enum
import re


class EdgeCase(enum.StrEnum):
    WRONG_NUMBER = "wrong_number"
    EXISTING_PATIENT = "existing_patient"
    MINOR = "minor"


PATTERNS: tuple[tuple[EdgeCase, re.Pattern[str]], ...] = (
    (
        EdgeCase.WRONG_NUMBER,
        re.compile(
            r"\b(wrong number|i did(n't| not) call a dentist|who is this"
            r"|i was (calling|trying to reach) (the |a )?(pharmacy|doctor|hospital|bank)"
            r"|sorry.{0,12}wrong)\b",
            re.I,
        ),
    ),
    (
        EdgeCase.EXISTING_PATIENT,
        re.compile(
            r"\b((i('m| am) )?(an? )?(existing|current) patient"
            r"|(reschedule|cancel|confirm|move) my appointment"
            r"|i have an appointment|about my appointment"
            r"|i('m| am) already a patient)\b",
            re.I,
        ),
    ),
    (
        EdgeCase.MINOR,
        re.compile(
            r"\b(i('m| am) (1[0-7]|[1-9]) (years old|yrs old)?"
            r"|i('m| am) (only )?(1[0-7])\b"
            r"|i('m| am) a minor"
            r"|i('m| am) still in (high school|middle school))\b",
            re.I,
        ),
    ),
)

# What the agent says. These are spoken verbatim, so they never vary between calls.
RESPONSES: dict[EdgeCase, str] = {
    EdgeCase.WRONG_NUMBER: ("Sorry about that, you have reached a dental office. Have a good day."),
    EdgeCase.EXISTING_PATIENT: (
        "It sounds like you are already a patient here. This line is for new enquiries, "
        "so please call the office directly and the front desk will take care of you."
    ),
    EdgeCase.MINOR: (
        "Thanks for calling. For treatment planning we need to speak with a parent or "
        "guardian, so please have them call us back. Take care."
    ),
}

OUTCOMES: dict[EdgeCase, str] = {
    EdgeCase.WRONG_NUMBER: "wrong_number",
    EdgeCase.EXISTING_PATIENT: "not_a_lead",
    EdgeCase.MINOR: "not_a_lead",
}


def detect(text: str) -> EdgeCase | None:
    """The first edge case the text plainly states, or None."""
    if not text:
        return None
    for case, pattern in PATTERNS:
        if pattern.search(text):
            return case
    return None


# Deepgram reports the detected language per result. Two Spanish utterances in a row is
# treated as a Spanish caller; one is treated as a stray word, because English speakers say
# "gracias" and a single detection is not worth ending an English call over.
SPANISH_UTTERANCES_TO_FALL_BACK = 2

# Spoken verbatim, never generated. A caller who has gone quiet should hear the same
# words every time, and neither line is a judgement call worth a model round trip.
SILENCE_REPROMPT = "Are you still there?"
SILENCE_GOODBYE = "I will let you go. Please call back any time. Goodbye."

SPANISH_FALLBACK = (
    "Gracias por llamar. Le vamos a devolver la llamada con alguien que habla espanol. "
    "Por favor marque su numero de telefono seguido de la tecla numeral."
)


class LanguageWatch:
    """Counts consecutive non-English detections."""

    def __init__(self, threshold: int = SPANISH_UTTERANCES_TO_FALL_BACK) -> None:
        self.threshold = threshold
        self.consecutive = 0
        self.language = "en"

    def observe(self, detected: str) -> bool:
        """Feed one transcript's detected language. True when the call should fall back."""
        if detected and detected.startswith("es"):
            self.consecutive += 1
            self.language = "es"
        elif detected:
            self.consecutive = 0
            self.language = detected
        return self.consecutive >= self.threshold
