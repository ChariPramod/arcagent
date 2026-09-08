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
