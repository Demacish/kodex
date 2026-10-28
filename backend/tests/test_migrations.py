"""Alembic owns the schema (kodex/core/migrations): head must match the
models, and a v1 database, which has tables but no alembic_version, must be
adopted without losing data, whatever drift it picked up from v1's
hand-run ALTER TABLEs."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.database import engine
from kodex.core.migrate import alembic_config, schema_differences, upgrade_database


@pytest.fixture
def scratch_engine():
    """An engine on a database of its own, so these tests can build and
    tear down schemas without touching the shared test database."""
    name = "kodex_migration_test"
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        connection.execute(text(f"CREATE DATABASE {name}"))
    scratch = create_engine(make_url(engine.url).set(database=name))
    try:
        yield scratch
    finally:
        scratch.dispose()
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))


def _run(scratch, alembic_command, revision):
    config = alembic_config()
    with scratch.begin() as connection:
        config.attributes["connection"] = connection
        alembic_command(config, revision)


HEAD = ScriptDirectory.from_config(alembic_config()).get_current_head()


def _current_revision(scratch) -> str:
    with scratch.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_head_matches_the_models():
    with engine.connect() as connection:
        assert schema_differences(connection) == []


def test_fresh_database_migrates_to_head(scratch_engine):
    assert upgrade_database(scratch_engine) == []
    assert _current_revision(scratch_engine) == HEAD


def test_v1_database_is_adopted_with_its_data(scratch_engine):
    # A v1 database the way the oldest live one looked: the baseline
    # schema, only some of app/migrations.py's late columns, the
    # hand-added edition_type, the FK without ON DELETE, no content_hash
    # index, and no alembic_version table at all.
    _run(scratch_engine, command.upgrade, "0001")
    with scratch_engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
        connection.execute(text("ALTER TABLE books ADD COLUMN content_hash VARCHAR(32)"))
        connection.execute(text("ALTER TABLE reading_progress ADD COLUMN chapter VARCHAR(255)"))
        connection.execute(
            text(
                "ALTER TABLE books ALTER COLUMN edition_type TYPE VARCHAR, ALTER COLUMN edition_type SET DEFAULT 'ISSUE'"
            )
        )
        connection.execute(text("ALTER TABLE requests DROP CONSTRAINT requests_download_id_fkey"))
        connection.execute(
            text(
                "ALTER TABLE requests ADD CONSTRAINT requests_download_id_fkey FOREIGN KEY (download_id) REFERENCES downloads (id)"
            )
        )
        connection.execute(
            text("INSERT INTO libraries (name, path, library_type) VALUES ('Serier', 'serier', 'COMICS')")
        )
        connection.execute(
            text(
                "INSERT INTO series (library_id, title, sort_title, path, comicvine_volume_id, is_following, "
                "new_release_available) VALUES (1, 'Saga', 'Saga', 'Saga', 43543, false, false)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO books (library_id, series_id, file_path, file_format, file_size, file_mtime, "
                "content_hash, number, edition_type) VALUES (1, 1, 'a.cbz', 'CBZ', 10, 1.0, 'abc', 12, 'COLLECTED')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO book_metadata (book_id, title, sort_title, authors, genres, tags, story_arcs, source) "
                "VALUES (1, 'Saga Vol. 2', 'Saga Vol. 2', '[]', '[]', '[]', '[]', 'MANUAL')"
            )
        )

    assert upgrade_database(scratch_engine) == []
    assert _current_revision(scratch_engine) == HEAD
    with scratch_engine.connect() as connection:
        row = connection.execute(text("SELECT file_path, content_hash, edition_type FROM books")).one()
    assert tuple(row) == ("a.cbz", "abc", "COLLECTED")
    indexes = {index["name"] for index in inspect(scratch_engine).get_indexes("books")}
    assert "ix_books_content_hash" in indexes
    with scratch_engine.connect() as connection:
        external = connection.execute(text("SELECT provider, external_id, is_primary FROM series_external_ids")).all()
        series_status = connection.execute(text("SELECT match_status FROM series")).scalar_one()
        book = connection.execute(text("SELECT format, number_label FROM books")).one()
        locked = connection.execute(text("SELECT locked_fields FROM book_metadata")).scalar_one()
    assert [tuple(r) for r in external] == [("comicvine", "43543", True)]
    assert series_status == "manual"
    assert tuple(book) == ("collected", "12")
    assert "summary" in locked


def test_migrating_twice_is_a_no_op(scratch_engine):
    assert upgrade_database(scratch_engine) == []
    assert upgrade_database(scratch_engine) == []


def test_downgrade_to_base_and_back(scratch_engine):
    upgrade_database(scratch_engine)
    _run(scratch_engine, command.downgrade, "base")
    assert set(inspect(scratch_engine).get_table_names()) == {"alembic_version"}
    assert upgrade_database(scratch_engine) == []
