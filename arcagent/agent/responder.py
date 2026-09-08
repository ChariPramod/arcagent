"""The agent as the audio loop sees it.

Implements ``arcagent.telephony.call_session.Responder`` over the LangGraph conversation,
and owns the edge case paths from scope section 3.8 that end a call before qualification.

Edge cases are checked before the graph runs. A caller saying "wrong number" should not
cost a model call, and more importantly should not have a lead record created for them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from arcagent.agent import edge_cases
from arcagent.agent.graph import AgentConfig, Conversation
from arcagent.agent.state import LeadFields
from arcagent.logging import get_logger

log = get_logger(__name__)


class GraphResponder:
    """Feeds caller transcripts into the graph and yields what the agent should say."""

    def __init__(self, config: AgentConfig) -> None:
        self.conversation = Conversation(config)
        self.language_watch = edge_cases.LanguageWatch()
        self._greeted = False
        self._edge_case: edge_cases.EdgeCase | None = None
        self._outcome: str | None = None

    @property
    def node_name(self) -> str | None:
        return self.conversation.state.get("current_node")

    @property
    def should_end(self) -> bool:
        return self._edge_case is not None or self.conversation.finished

    @property
    def outcome(self) -> str | None:
        return self._outcome or self.conversation.outcome

    @property
    def fields(self) -> LeadFields:
        return self.conversation.fields

    @property
    def creates_a_lead(self) -> bool:
        """A wrong number or an existing patient is not a lead and gets no lead row."""
        return self._edge_case is None

    async def greet(self) -> AsyncIterator[str]:
        """The disclosure, spoken before the caller has said anything."""
        self._greeted = True
        for line in await self.conversation.start():
            yield line

    async def respond(self, transcript: str) -> AsyncIterator[str]:
        """One caller turn."""
        if not self._greeted:
            async for line in self.greet():
                yield line
            if not transcript:
                return

        case = edge_cases.detect(transcript)
        if case is not None:
            self._edge_case = case
            self._outcome = edge_cases.OUTCOMES[case]
            log.info("edge_case_detected", case=str(case))
            yield edge_cases.RESPONSES[case]
            return

        for line in await self.conversation.say(transcript):
            yield line

    def observe_language(self, detected: str) -> bool:
        """Feed Deepgram's detected language. True when the call should fall back."""
        if not self.language_watch.observe(detected):
            return False
        self._edge_case = None
        self._outcome = "language_fallback"
        return True
