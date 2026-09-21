"""Evaluation entrypoints reject unfinished inputs before opening paid services."""

from argparse import Namespace

import pytest

from arcagent.agent import prompts
from arcagent.agent.readiness import REQUIRED_PROMPTS
from arcagent.config import Settings
from evals import mutations, run_audio, run_text


@pytest.mark.parametrize("entrypoint", [run_text, mutations])
@pytest.mark.parametrize("content", [None, "", "TODO_OWNER: finish these instructions"])
async def test_unready_prompt_fails_before_vendor_construction(
    tmp_path, monkeypatch, entrypoint, content
):
    version = tmp_path / "v999"
    version.mkdir()
    for name in REQUIRED_PROMPTS - {"system"}:
        (version / f"{name}.md").write_text("Complete test instructions")
    if content is not None:
        (version / "system.md").write_text(content)
    monkeypatch.setattr(prompts, "PROMPTS_ROOT", tmp_path)
    prompts.load_prompt.cache_clear()
    monkeypatch.setattr(
        entrypoint, "get_settings", lambda: Settings(_env_file=None, llm_api_key="")
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("vendor constructed with unfinished prompts")

    monkeypatch.setattr(entrypoint, "AnthropicStructuredLLM", forbidden)
    args = Namespace(
        list=False,
        run_name="readiness",
        repeats=1,
        concurrency=1,
        prompts="v999",
        groups=None,
        ids=None,
    )
    try:
        with pytest.raises(SystemExit, match="prompt"):
            await entrypoint.run(args)
    finally:
        prompts.load_prompt.cache_clear()


async def test_audio_empty_selection_fails_before_credentials_or_vendors(tmp_path, monkeypatch):
    from evals import persona

    monkeypatch.setattr(persona, "PERSONAS_DIR", tmp_path)
    monkeypatch.setattr(run_audio, "get_settings", lambda: Settings(_env_file=None))

    def forbidden(*args, **kwargs):
        raise AssertionError("vendor constructed for empty suite")

    monkeypatch.setattr(run_audio, "CartesiaTTS", forbidden)
    with pytest.raises(SystemExit, match="no personas"):
        await run_audio.run(
            Namespace(stream_url=run_audio.DEFAULT_STREAM_URL, n=1, groups=None, ids=None)
        )


async def test_text_empty_selection_is_reported_before_missing_credentials(
    tmp_path, monkeypatch, ready_prompts
):
    from evals import persona

    empty = tmp_path / "empty-personas"
    empty.mkdir()
    monkeypatch.setattr(persona, "PERSONAS_DIR", empty)
    monkeypatch.setattr(run_text, "get_settings", lambda: Settings(_env_file=None, llm_api_key=""))
    with pytest.raises(SystemExit, match="no personas"):
        await run_text.run(Namespace(repeats=1, concurrency=1, prompts="v1", groups=None, ids=None))


async def test_audio_does_not_require_local_copy_of_remote_prompts(tmp_path, monkeypatch):
    from pathlib import Path

    from evals import persona

    monkeypatch.setattr(prompts, "PROMPTS_ROOT", tmp_path)
    monkeypatch.setattr(persona, "PERSONAS_DIR", Path(__file__).parent / "fixtures" / "personas")
    monkeypatch.setattr(
        run_audio, "get_settings", lambda: Settings(_env_file=None, audio_eval_token="")
    )
    with pytest.raises(SystemExit, match="AUDIO_EVAL_TOKEN"):
        await run_audio.run(
            Namespace(
                stream_url=run_audio.DEFAULT_STREAM_URL, n=1, groups=None, ids=None, prompts="v999"
            )
        )
