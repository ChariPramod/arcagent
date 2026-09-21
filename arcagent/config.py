"""Application settings.

Every credential and environment specific value is read from the environment.
Nothing in this repo hardcodes a key, a phone number, or a URL.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment variables, or a local .env file in dev."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Environment
    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_number: str = ""
    coordinator_number: str = ""
    validate_twilio_signature: bool = True
    echo_enabled: bool = False
    enable_audio_evals: bool = False
    audio_eval_token: str = Field(default="", repr=False)

    # Speech vendors
    deepgram_api_key: str = ""
    cartesia_api_key: str = ""

    # LLM
    llm_api_key: str = ""
    llm_model: str = "claude-haiku-4-5"
    llm_model_extraction: str = "claude-opus-5"

    # Infrastructure
    database_url: str = "postgresql+psycopg://arcagent:arcagent@localhost:5432/arcagent"
    public_url: str = ""

    # Server-to-server credential for the read-only product console.
    console_api_token: str = Field(default="", repr=False)
    admin_api_token: str = Field(default="", repr=False)

    # Conversation behaviour
    prompt_version: str = "v1"
    handoff_threshold: int = 60
    coordinator_available: bool = True
    silence_reprompt_s: float = 8.0
    silence_hangup_s: float = 15.0
    barge_in_min_words: int = 3

    # Vendor parameters. Names are verified in docs/vendor_params.md.
    deepgram_endpointing_ms: int = 400
    deepgram_utterance_end_ms: int = 1000
    cartesia_voice_id: str = ""
    cartesia_model_id: str = "sonic-2"

    # Compliance
    transcript_retention_days: int = Field(default=30, ge=1)

    @property
    def stream_url(self) -> str:
        """WebSocket URL Twilio connects back to, derived from PUBLIC_URL."""
        host = self.public_url.replace("https://", "").replace("http://", "").rstrip("/")
        return f"wss://{host}/voice/stream"


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance. Call ``get_settings.cache_clear()`` in tests."""
    return Settings()
