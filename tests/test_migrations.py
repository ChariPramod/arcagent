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
        ("eval_runs", {"git_sha", "prompt_version", "threshold", "tier", "snapshot"}),
        ("eval_results", {"transcript"}),
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


def test_transcript_migration_preserves_legacy_results_and_can_be_reversed(tmp_path: Path) -> None:
    from sqlalchemy import text

    from alembic import command

    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    config = _alembic_config(database_url)
    command.upgrade(config, "e31339b35a93")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO eval_runs (id, run_name, git_sha, prompt_version, threshold, tier) "
                    "VALUES (1, 'legacy', 'fixture', 'v1', 60, 'TEXT')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO eval_results (id, run_id, scenario_id, repeat_index, passed) "
                    "VALUES (1, 1, 'legacy', 0, 1)"
                )
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT scenario_id, passed, transcript FROM eval_results")
            ).one() == ("legacy", 1, None)
        command.downgrade(config, "e31339b35a93")
        assert "transcript" not in {c["name"] for c in inspect(engine).get_columns("eval_results")}
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT scenario_id FROM eval_results")).scalar_one()
                == "legacy"
            )
        command.upgrade(config, "head")
    finally:
        engine.dispose()


def test_snapshot_migration_preserves_legacy_runs_and_round_trips_json(tmp_path: Path) -> None:
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from alembic import command
    from arcagent.persistence.models import EvalRun
    from tests.test_eval_snapshots import snapshot_payload

    database_url = f"sqlite:///{tmp_path / 'snapshots.db'}"
    config = _alembic_config(database_url)
    command.upgrade(config, "742a8b19c6d0")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO eval_runs (id, run_name, git_sha, prompt_version, threshold, tier) "
                    "VALUES (1, 'legacy', 'fixture', 'v1', 60, 'TEXT')"
                )
            )
        command.upgrade(config, "head")
        payload = snapshot_payload()
        with Session(engine) as session:
            run = session.get(EvalRun, 1)
            assert run.snapshot is None
            run.snapshot = payload
            session.commit()
        with Session(engine) as session:
            assert session.get(EvalRun, 1).snapshot == payload
        command.downgrade(config, "742a8b19c6d0")
        assert "snapshot" not in {c["name"] for c in inspect(engine).get_columns("eval_runs")}
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT run_name FROM eval_runs")).scalar_one() == "legacy"
            )
        command.upgrade(config, "head")
    finally:
        engine.dispose()


def test_snapshot_migration_uses_jsonb_on_postgres() -> None:
    from io import StringIO

    from alembic import command

    config = _alembic_config("postgresql+psycopg://")
    config.output_buffer = StringIO()
    command.upgrade(config, "742a8b19c6d0:head", sql=True)
    assert "ALTER TABLE eval_runs ADD COLUMN snapshot JSONB" in config.output_buffer.getvalue()
