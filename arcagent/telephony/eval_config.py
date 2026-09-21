"""Allowlisted effective server configuration for isolated audio evaluations.

Hashes identify the captured inputs and source files, not deterministic replay or remote
vendor versions. Cached prompt strings are the same strings used by the live graph.
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from arcagent.agent.llm import MAX_TOKENS_TURN
from arcagent.agent.prompts import load_prompt
from arcagent.config import Settings
from arcagent.speech.cartesia_tts import CARTESIA_VERSION, OUTPUT_FORMAT
from arcagent.speech.deepgram_stt import build_stream_url
from arcagent.telephony.call_session import CallSession

PROMPT_NAMES = frozenset(
    {
        "system",
        "greeting",
        "confirm_treatment_interest",
        "assess_situation",
        "extract_insurance_signal",
        "capture_contact",
        "handle_objection",
    }
)
SOURCE_ROOT = Path(__file__).resolve().parents[1]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SourcePath = Annotated[str, Field(pattern=r"^arcagent/(?:[a-zA-Z0-9_]+/)*[a-zA-Z0-9_]+\.py$")]


class ConfigValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PromptHash(ConfigValue):
    sha256: Sha256


class DeepgramConfig(ConfigValue):
    encoding: str
    sample_rate: str
    channels: str
    model: str
    interim_results: str
    smart_format: str
    vad_events: str
    endpointing: str
    utterance_end_ms: str


class CartesiaConfig(ConfigValue):
    model_id: str
    voice_id: str
    api_version: str
    encoding: str
    container: str
    sample_rate: int


class SpeechConfig(ConfigValue):
    deepgram: DeepgramConfig
    cartesia: CartesiaConfig


class TurnConfig(ConfigValue):
    silence_reprompt_s: float
    silence_hangup_s: float
    barge_in_min_words: int
    playback_timeout_s: float


class AudioServerConfig(ConfigValue):
    schema_version: Literal[1]
    prompt_version: str
    threshold: int
    coordinator_available: bool
    agent_model: str
    agent_max_tokens: int
    prompts: dict[str, PromptHash]
    speech: SpeechConfig
    turns: TurnConfig
    source_hashes: dict[SourcePath, Sha256] = Field(min_length=1)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("server configuration version must be an integer")
        return value

    @model_validator(mode="after")
    def required_prompts(self) -> Self:
        if set(self.prompts) != PROMPT_NAMES:
            raise ValueError("server configuration must identify every required prompt")
        return self


def build_eval_config(settings: Settings, coordinator_available: bool) -> dict:
    """Capture only agent inputs; never serialize Settings or vendor auth headers."""
    prompts = {
        name: {
            "sha256": hashlib.sha256(
                load_prompt(name, settings.prompt_version).encode()
            ).hexdigest()
        }
        for name in sorted(PROMPT_NAMES)
    }
    sources = {
        "arcagent/" + path.relative_to(SOURCE_ROOT).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(SOURCE_ROOT.rglob("*.py"))
    }
    return AudioServerConfig(
        schema_version=1,
        prompt_version=settings.prompt_version,
        threshold=settings.handoff_threshold,
        coordinator_available=coordinator_available,
        agent_model=settings.llm_model,
        agent_max_tokens=MAX_TOKENS_TURN,
        prompts=prompts,
        speech=SpeechConfig(
            deepgram=DeepgramConfig(**dict(parse_qsl(urlsplit(build_stream_url(settings)).query))),
            cartesia=CartesiaConfig(
                model_id=settings.cartesia_model_id,
                voice_id=settings.cartesia_voice_id,
                api_version=CARTESIA_VERSION,
                **OUTPUT_FORMAT,
            ),
        ),
        turns=TurnConfig(
            silence_reprompt_s=settings.silence_reprompt_s,
            silence_hangup_s=settings.silence_hangup_s,
            barge_in_min_words=settings.barge_in_min_words,
            playback_timeout_s=inspect.signature(CallSession)
            .parameters["playback_timeout_s"]
            .default,
        ),
        source_hashes=sources,
    ).model_dump()
