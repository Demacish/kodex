# 0003. SQLAlchemy 2.1, Alembic and Pydantic 2

Status: Accepted

## Context

v1 created tables with `create_all()` and patched existing databases with
hand-written `ALTER TABLE`s and a startup column-adder, which drifted (live
databases differed from the models).

## Decision

SQLAlchemy 2.1, Alembic 1.20 and Pydantic 2.14. Alembic owns the schema from
phase 0: revision 0001 is the v1 schema, 0002 adds v1's late columns and
reconciles known drift idempotently. `python -m kodex.core.migrate` adopts v1
databases (stamp at 0001, then upgrade) under an advisory lock and reports any
remaining difference from the models. Constraint names follow PostgreSQL's
defaults through a naming convention.

## Consequences

Every schema change is a reviewed migration; `tests/test_migrations.py` fails
when head and models differ and covers v1 adoption.
