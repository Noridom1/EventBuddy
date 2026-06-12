import pytest
from sqlalchemy import text

import eventbuddy.domain.models  # noqa: F401  (registers every table on Base.metadata)
from eventbuddy.data.db import Base, engine


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate all tables before each integration test so the suite is isolated
    and rerunnable against a shared Postgres (session_scope commits on exit)."""
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    if tables:
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield
