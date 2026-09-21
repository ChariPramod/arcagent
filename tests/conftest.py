"""Shared fixtures.

The suite runs against an in memory SQLite database created from the models, so it needs
no Docker and no Postgres. Migrations are exercised separately in test_migrations.py.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from arcagent.persistence.models import Base


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def ready_prompts(tmp_path, monkeypatch):
    """Provide syntactically ready test prompts without approving production wording.

    Only tests intending to enter the runnable pipeline request this fixture. Keeping
    the remaining fixture text preserves existing dialogue assertions while the real
    owner-authored prompt files remain untouched and correctly fail readiness checks.
    """
    from arcagent.agent import prompts

    root = tmp_path / "ready-prompts"
    version = root / "v1"
    version.mkdir(parents=True)
    for source in (prompts.PROMPTS_ROOT / "v1").glob("*.md"):
        if source.name == "README.md":
            continue
        text = "\n".join(
            line
            for line in source.read_text(encoding="utf-8").splitlines()
            if not line.startswith("TODO_OWNER:")
        )
        (version / source.name).write_text(text, encoding="utf-8")
    monkeypatch.setattr(prompts, "PROMPTS_ROOT", root)
    prompts.load_prompt.cache_clear()
    try:
        yield root
    finally:
        prompts.load_prompt.cache_clear()
