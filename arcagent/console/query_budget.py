"""Transaction-local budgets for potentially broad authenticated console reads."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def limit_query_time(session: Session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET LOCAL statement_timeout = '3s'"))
        session.execute(text("SET LOCAL lock_timeout = '1s'"))
