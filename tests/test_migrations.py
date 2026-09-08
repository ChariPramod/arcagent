"""The migration chain builds the same schema the models declare.

Guards against a model change landing without a migration, which would work in the suite
and fail on a real deployment.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from arcagent.persistence.models import Base

REPO_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_there_is_exactly_one_head() -> None:
    """Two heads means someone branched the migration chain and did not merge it."""
    script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
    assert len(script.get_heads()) == 1


def test_migrations_build_every_table_the_models_declare(tmp_path: Path) -> None:
    from alembic import command

    database_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    command.upgrade(_alembic_config(database_url), "head")

    engine = create_engine(database_url, future=True)
    try:
        migrated = set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()

    assert migrated == set(Base.metadata.tables)


@pytest.mark.parametrize(
    "table,columns",
    [
        ("turns", {"stt_final_ms", "llm_ttft_ms", "tts_first_byte_ms", "playback_start_ms"}),
        ("calls", {"from_number_hash", "outcome", "final_node"}),
        ("lead_scores", {"score", "threshold_used", "decision", "score_breakdown"}),
        ("eval_runs", {"git_sha", "prompt_version", "threshold", "tier"}),
    ],
)
def test_migrated_columns_match_the_models(tmp_path: Path, table: str, columns: set[str]) -> None:
    from alembic import command

    database_url = f"sqlite:///{tmp_path / f'{table}.db'}"
    command.upgrade(_alembic_config(database_url), "head")
    engine = create_engine(database_url, future=True)
    try:
        present = {c["name"] for c in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()
    assert columns <= present
