"""Prompt loading.

Prompts are owner authored markdown under ``v<N>/``. A version directory that an eval run
has been tagged with is never edited; a change is a new directory.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_ROOT = Path(__file__).parent


class PromptNotFound(FileNotFoundError):
    """A node asked for a prompt file that does not exist in that version."""


@lru_cache(maxsize=128)
def load_prompt(name: str, version: str = "v1") -> str:
    """Read ``prompts/<version>/<name>.md``.

    Cached, because a prompt is read on every turn and does not change inside a process.
    Call ``load_prompt.cache_clear()`` after editing a prompt in the REPL.

    Raises:
        PromptNotFound: no such prompt in that version.
    """
    path = PROMPTS_ROOT / version / f"{name}.md"
    if not path.is_file():
        raise PromptNotFound(f"no prompt {name!r} in version {version!r} at {path}")
    return path.read_text(encoding="utf-8").strip()


def available_versions() -> list[str]:
    """Version directories present, sorted. Used by the harness to tag a run."""
    return sorted(p.name for p in PROMPTS_ROOT.iterdir() if p.is_dir() and p.name.startswith("v"))
