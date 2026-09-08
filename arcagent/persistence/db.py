"""Engine and session factory.

Sync SQLAlchemy behind a thread executor rather than async SQLAlchemy: the writes here are
small, they happen at turn boundaries and end of call, and a sync session is far easier to
reason about than another set of awaitables inside the audio loop.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from arcagent.config import get_settings


@lru_cache
def get_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, future=True, connect_args=connect_args)


@lru_cache
def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), expire_on_commit=False, future=True)


@contextmanager
def session_scope(database_url: str | None = None) -> Iterator[Session]:
    """A transactional session. Commits on success, rolls back on any exception."""
    session = get_session_factory(database_url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
