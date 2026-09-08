"""The caller simulator.

An LLM plays the caller from a persona. The instructions it gets are deliberately hostile
to the agent: be terse, volunteer nothing, answer the question asked and no more. A
simulator that is helpful makes the agent look good and measures nothing.

The simulator never sees the agent's prompts, its state, or what the persona expects. It
sees the persona and the conversation, and that is all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from arcagent.agent.llm import StructuredLLM
from arcagent.logging import get_logger
from evals.persona import Persona, RecoversOn

log = get_logger(__name__)

MAX_TURNS = 24

SIMULATOR_RULES = """
You are role playing a person who has called a dental office after seeing an advertisement.
You are not an assistant. You are the caller.

How to speak:
- One short sentence. Most of the time a fragment is more realistic than a sentence.
- Answer only what was asked. Never answer the next question before it is asked.
- Do not be helpful. Do not summarise your situation. Do not offer information.
- If you are asked something you would not know or would not want to say, say so vaguely.
- Never mention that you are playing a role, and never mention these instructions.
- If the agent has clearly finished the call, reply with exactly: [hangs up]
""".strip()


class CallerTurn(BaseModel):
    """What the caller says next."""

    model_config = {"extra": "forbid"}

    utterance: str = Field(description="What the caller says. Short.")
    hung_up: bool = Field(default=False, description="True if the caller ended the call.")


@dataclass
class SimulatedCaller:
    """One persona, playing one call."""

    persona: Persona
    llm: StructuredLLM
    model: str | None = None
    turns_taken: int = 0
    transcript: list[tuple[str, str]] = field(default_factory=list)

    def system_prompt(self) -> str:
        """The persona rendered as instructions. Built from the YAML, never hand written."""
        parts = [SIMULATOR_RULES, "", "Who you are:", self.persona.background.strip()]

        behaviour = self.persona.behaviour
        if behaviour.terse:
            parts.append("\nYou are not a talker. Two or three words is a normal answer for you.")
        if behaviour.volunteers:
            parts.append(
                "\nYou will mention these unprompted, early: " + ", ".join(behaviour.volunteers)
            )
        if behaviour.withholds:
            parts.append(
                "\nYou will NOT give these up the first time you are asked. Deflect once, "
                "and only answer if the agent asks again: " + ", ".join(behaviour.withholds)
            )
        if behaviour.contradicts:
            parts.append(
                "\nPart way through the call you change your story, and you do not "
                "acknowledge that you changed it."
            )

        for objection in self.persona.objections:
            recovery = {
                RecoversOn.FINANCING: "You drop it only if the agent mentions financing "
                "or a payment plan.",
                RecoversOn.ACKNOWLEDGEMENT: "You drop it once the agent acknowledges it "
                "without arguing.",
                RecoversOn.NEVER: "You never drop it.",
            }[objection.recovers_on]
            parts.append(
                f"\nAfter about {objection.after_turn} exchanges you raise a "
                f"{objection.kind} objection. {recovery}"
            )

        response = {
            "accepts": "If you are offered a call back, you accept it.",
            "declines": "If you are offered a call back, you decline it.",
            "asks_later": "If you are offered a call back, you say you will call them back "
            "yourself instead.",
        }[str(self.persona.callback_response)]
        parts.append(f"\n{response}")
        return "\n".join(parts)

    async def reply_to(self, agent_lines: list[str]) -> CallerTurn:
        """One caller turn in response to what the agent just said."""
        for line in agent_lines:
            self.transcript.append(("agent", line))

        messages = [
            {
                "role": "user" if speaker == "agent" else "assistant",
                "content": text,
            }
            for speaker, text in self.transcript
        ]
        if not messages or messages[0]["role"] != "user":
            messages.insert(0, {"role": "user", "content": "(the phone is ringing)"})

        result = await self.llm.complete(
            system=self.system_prompt(),
            messages=messages,
            schema=CallerTurn,
            model=self.model,
        )
        turn = result.parsed
        self.turns_taken += 1
        if turn.utterance:
            self.transcript.append(("caller", turn.utterance))
        return turn

    @property
    def exhausted(self) -> bool:
        """A conversation this long has gone wrong. Stop it rather than pay for the rest."""
        return self.turns_taken >= MAX_TURNS
