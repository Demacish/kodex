"""jobs

Background jobs move from Redis/RQ into PostgreSQL: Procrastinate's schema
(tables, types, functions and triggers, as Procrastinate 3.10.0 ships it,
vendored next to this file) and job_results, which keeps what a job
returned or the error it failed with. A later Procrastinate release brings
its own migration files; each gets an Alembic migration applying it.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = Path(__file__).with_name("procrastinate_3_10_0_schema.sql")


def upgrade() -> None:
    # Run as the driver gets it, without parameters: the schema has PL/pgSQL
    # bodies, casts and percent signs that must not be interpreted.
    with op.get_bind().connection.dbapi_connection.cursor() as cursor:  # type: ignore[union-attr]
        cursor.execute(_SCHEMA.read_text())
    op.create_table(
        "job_results",
        sa.Column("job_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("job_id", name="job_results_pkey"),
    )


def downgrade() -> None:
    op.drop_table("job_results")
    schema = _SCHEMA.read_text()
    bind = op.get_bind()
    for name in re.findall(r"CREATE (?:UNLOGGED )?TABLE (\w+)", schema):
        bind.exec_driver_sql(f"DROP TABLE IF EXISTS {name} CASCADE")
    for name in re.findall(r"CREATE (?:OR REPLACE )?FUNCTION (\w+)", schema):
        bind.exec_driver_sql(f"DROP FUNCTION IF EXISTS {name} CASCADE")
    for name in re.findall(r"CREATE TYPE (\w+)", schema):
        bind.exec_driver_sql(f"DROP TYPE IF EXISTS {name} CASCADE")
