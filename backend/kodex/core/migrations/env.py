"""Alembic environment: migrates the database DATABASE_URL points to (the
same engine the app uses), against the models' metadata."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

import app.models  # noqa: F401 - registers every table on Base.metadata
from kodex.core.db import Base, engine
from kodex.core.migrate import include_name

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=engine.url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # kodex.core.migrate passes its already-locked connection in; the
    # plain `alembic` CLI doesn't, and gets one of its own.
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    with engine.connect() as connection:
        _run(connection)


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True, include_name=include_name
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
