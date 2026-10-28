"""The test database: one PostgreSQL database for the whole run (pointed
to by TEST_DATABASE_URL, see tests/conftest.py), emptied before each test
that asks for it. Tests never run against SQLite."""

from __future__ import annotations

from sqlalchemy import Engine, text

from app.database import Base, engine


def reset_database() -> None:
    """Empties every table and restarts their id sequences.

    A session some earlier code forgot to close keeps its transaction (and
    its locks) open, which would make TRUNCATE wait forever. Such leftover
    connections are terminated first; they belong to tests that already
    finished.
    """
    tables = ", ".join(f'"{name}"' for name in Base.metadata.tables)
    with engine.begin() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                "AND state IN ('idle in transaction', 'idle in transaction (aborted)')"
            )
        )
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def fresh_engine() -> Engine:
    """The shared test engine, with every table emptied first."""
    reset_database()
    return engine
