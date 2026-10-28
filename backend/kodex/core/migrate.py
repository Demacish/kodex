"""Brings the database schema up to date: `python -m kodex.core.migrate`.

Runs before the API starts (see backend/Dockerfile). A v1 database has
tables but no alembic_version; it is stamped at the v1 baseline (0001)
first, and 0002 then adds whatever v1 columns it lacks. Afterwards the
schema is compared with the models and any remaining difference is logged,
so a database that drifted in some unknown way doesn't go unnoticed.

`python -m kodex.core.migrate check` only compares, and exits 1 on a
difference (used in CI).
"""

from __future__ import annotations

import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, Engine, inspect, text

logger = logging.getLogger(__name__)

V1_BASELINE = "0001"
# Serialises concurrent migrators (two containers starting at once).
_ADVISORY_LOCK_ID = 0x4B4F444558  # "KODEX"


def alembic_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))


def include_name(name: str | None, type_: str, parent_names: Any) -> bool:
    """Procrastinate's tables are its own (migration 0005), not models; the
    search indexes on expressions (migration 0013) aren't in the models
    either, as Alembic can't compare them."""
    if type_ == "table" and (name or "").startswith("procrastinate_"):
        return False
    return not (type_ == "index" and (name or "").endswith(("_trgm", "_fts")))


def schema_differences(connection: Connection) -> list[Any]:
    """Alembic's autogenerate diff between the database and the models;
    empty when they match."""
    import app.models  # noqa: F401 - registers every table on Base.metadata
    from kodex.core.db import Base

    context = MigrationContext.configure(connection, opts={"compare_type": True, "include_name": include_name})
    differences: list[Any] = compare_metadata(context, Base.metadata)
    return differences


def upgrade_database(engine: Engine | None = None) -> list[Any]:
    """Migrates to head and returns the remaining schema differences."""
    if engine is None:
        from kodex.core.db import engine as app_engine

        engine = app_engine

    config = alembic_config()
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _ADVISORY_LOCK_ID})
        config.attributes["connection"] = connection
        tables = set(inspect(connection).get_table_names())
        if "alembic_version" not in tables and "books" in tables:
            logger.info("Adopting a v1 database: stamping it at revision %s", V1_BASELINE)
            command.stamp(config, V1_BASELINE)
        command.upgrade(config, "head")
        differences = schema_differences(connection)
    _seal_secrets(engine)
    for difference in differences:
        logger.error("Database schema differs from the models: %s", difference)
    return differences


@lru_cache(maxsize=1)
def head_revision() -> str | None:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def readiness() -> str | None:
    """Why the server isn't ready for traffic, or None when it is: the
    database must answer and be at the migrations' head."""
    from kodex.core.db import engine

    try:
        with engine.connect() as connection:
            current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as exc:  # noqa: BLE001 - any failure means not ready
        return f"database: {type(exc).__name__}"
    if current != head_revision():
        return f"schema at {current}, migrations at {head_revision()}"
    return None


def _seal_secrets(engine: Engine) -> None:
    """Secrets kept from before SECRET_KEY was set get sealed now (kodex.core.sealed)."""
    from sqlalchemy.orm import Session

    from kodex.core.auth.factors import seal_stored_secrets

    with Session(engine) as db:
        count = seal_stored_secrets(db)
    if count:
        logger.info("Sealed %d authenticator secret(s) with SECRET_KEY", count)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Its per-sequence "assuming SERIAL" notes are noise on every start.
    logging.getLogger("alembic.ddl").setLevel(logging.WARNING)
    if argv[1:] == ["check"]:
        from kodex.core.db import engine

        with engine.connect() as connection:
            differences = schema_differences(connection)
        for difference in differences:
            print(difference)
        return 1 if differences else 0
    upgrade_database()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
