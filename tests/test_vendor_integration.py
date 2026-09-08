"""Live vendor checks. Skipped unless RUN_INTEGRATION=1 and a real key is present.

These are the only tests that spend money. Run them yourself:

    RUN_INTEGRATION=1 pytest tests/test_vendor_integration.py -v
"""

from __future__ import annotations

import asyncio
import os

import pytest

from arcagent.config import Settings
from arcagent.speech.deepgram_stt import DeepgramSTT, TranscriptEvent

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="set RUN_INTEGRATION=1 to run live vendor checks",
)

# 20 ms of mulaw silence, the frame Twilio sends when nobody is talking.
SILENT_FRAME = bytes([0xFF]) * 160


@pytest.mark.timeout(60)
async def test_deepgram_accepts_mulaw_8k_and_answers() -> None:
    """Proves the parameter names in docs/vendor_params.md section 2 are accepted live."""
    settings = Settings()
    if not settings.deepgram_api_key:
        pytest.skip("DEEPGRAM_API_KEY is not set")

    received: list[object] = []
    async with DeepgramSTT(settings) as stt:

        async def pump() -> None:
            for _ in range(100):  # two seconds of audio
                await stt.send_audio(SILENT_FRAME)
                await asyncio.sleep(0.02)

        pump_task = asyncio.create_task(pump())
        try:
            async with asyncio.timeout(30):
                async for event in stt:
                    received.append(event)
                    if isinstance(event, TranscriptEvent):
                        break
        except TimeoutError:
            pass
        finally:
            pump_task.cancel()

    assert stt.dropped_frames == 0, "Deepgram rejected frames, check encoding parameters"
    assert received, "Deepgram accepted the connection but sent no events"
