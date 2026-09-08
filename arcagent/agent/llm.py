"""Structured LLM calls.

Every agent node asks for JSON matching a Pydantic schema. Nothing parses free text, so a
node cannot invent a field name and nothing downstream has to guess what the model meant.

The call is streamed even though the whole JSON object is needed before the agent can
speak, because the first token timestamp is the ``llm_ttft_ms`` column in the latency
budget and it is not measurable any other way.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from arcagent.config import Settings
from arcagent.logging import get_logger

log = get_logger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# A qualification turn has to be spoken inside the latency budget, so turn generation runs
# on the fast model. The end of call extraction pass is not on the critical path and runs
# on the strong one. Both ids come from settings.
MAX_TOKENS_TURN = 1024


class LLMError(RuntimeError):
    """The model call failed or returned something that did not match the schema."""


@dataclass(frozen=True, slots=True)
class LLMResult(Generic[SchemaT]):
    """A parsed response plus the timings the latency table needs."""

    parsed: SchemaT
    ttft_s: float | None
    total_s: float
    raw: str


class StructuredLLM(Protocol):
    """What a node needs from a model. Implemented for real and faked in tests."""

    async def complete(
        self,
        system: str,
        messages: Sequence[dict[str, Any]],
        schema: type[SchemaT],
        model: str | None = None,
    ) -> LLMResult[SchemaT]: ...


class AnthropicStructuredLLM:
    """Structured outputs over the Anthropic Messages API.

    The client is created lazily so importing this module never requires a key, which keeps
    the whole test suite runnable offline.
    """

    def __init__(
        self,
        settings: Settings,
        client: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._client = client
        self._clock = clock

    def _get_client(self) -> Any:
        if self._client is None:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=self._settings.llm_api_key)
        return self._client

    async def complete(
        self,
        system: str,
        messages: Sequence[dict[str, Any]],
        schema: type[SchemaT],
        model: str | None = None,
    ) -> LLMResult[SchemaT]:
        """Ask for one JSON object matching ``schema``.

        Raises:
            LLMError: the call failed, or the response did not validate against the schema.
        """
        import anthropic

        started = self._clock()
        first_token_at: float | None = None
        chunks: list[str] = []

        try:
            async with self._get_client().messages.stream(
                model=model or self._settings.llm_model,
                max_tokens=MAX_TOKENS_TURN,
                system=system,
                messages=list(messages),
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": _json_schema(schema),
                    }
                },
            ) as stream:
                async for text in stream.text_stream:
                    if first_token_at is None:
                        first_token_at = self._clock()
                    chunks.append(text)
        except anthropic.APIStatusError as exc:
            raise LLMError(f"model call failed with {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("model call could not reach the API") from exc

        raw = "".join(chunks)
        return LLMResult(
            parsed=parse_or_raise(raw, schema),
            ttft_s=None if first_token_at is None else first_token_at - started,
            total_s=self._clock() - started,
            raw=raw,
        )


def _json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Pydantic's schema, tightened the way structured outputs requires."""
    generated = schema.model_json_schema()
    generated["additionalProperties"] = False
    return generated


def parse_or_raise(raw: str, schema: type[SchemaT]) -> SchemaT:
    """Validate a JSON string against a node schema.

    Raises:
        LLMError: the text was not JSON, or did not match the schema. Either way the node
            cannot proceed, and a partially applied update would be worse than none.
    """
    try:
        return schema.model_validate_json(raw)
    except ValidationError as exc:
        raise LLMError(
            f"response did not match {schema.__name__}: {exc.error_count()} errors"
        ) from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise LLMError(f"response was not valid JSON for {schema.__name__}") from exc
