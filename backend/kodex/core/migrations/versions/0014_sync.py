"""delta sync for apps, file digests, app login

sync_log, written by triggers on libraries, series, books (and their
metadata) and collections (and their books), and seeded with everything
there is, so a client starting from cursor 0 gets the whole catalog
(kodex.core.sync). books get a cached SHA-256 of their file for verifying
downloads, and auth_challenges a label (an app's device name while it
logs in).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, entity, id column, whether deleting the row deletes the entity)
_SOURCES = (
    ("libraries", "library", "id", True),
    ("series", "series", "id", True),
    ("books", "book", "id", True),
    ("book_metadata", "book", "book_id", False),
    ("collections", "collection", "id", True),
    ("collection_books", "collection", "collection_id", False),
)

_FUNCTION = """
CREATE FUNCTION kodex_sync_log() RETURNS trigger AS $$
DECLARE
    row_id integer;
BEGIN
    IF TG_OP = 'DELETE' THEN
        EXECUTE format('SELECT ($1).%I', TG_ARGV[1]) INTO row_id USING OLD;
    ELSE
        EXECUTE format('SELECT ($1).%I', TG_ARGV[1]) INTO row_id USING NEW;
    END IF;
    INSERT INTO sync_log (entity, entity_id, deleted)
    VALUES (TG_ARGV[0], row_id, TG_OP = 'DELETE' AND TG_ARGV[2] = 'self');
    RETURN NULL;
END
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.create_table(
        "sync_log",
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("entity", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("seq", name="sync_log_pkey"),
    )
    op.create_index("ix_sync_log_entity_entity_id", "sync_log", ["entity", "entity_id"])
    op.execute(_FUNCTION)
    for table, entity, column, owns in _SOURCES:
        kind = "self" if owns else "parent"
        op.execute(
            f"CREATE TRIGGER {table}_sync_write AFTER INSERT OR DELETE ON {table} FOR EACH ROW "
            f"EXECUTE FUNCTION kodex_sync_log('{entity}', '{column}', '{kind}')"
        )
        op.execute(
            f"CREATE TRIGGER {table}_sync_update AFTER UPDATE ON {table} FOR EACH ROW "
            f"WHEN (OLD::text IS DISTINCT FROM NEW::text) EXECUTE FUNCTION kodex_sync_log('{entity}', '{column}', '{kind}')"
        )
    for table, entity, column, owns in _SOURCES:
        if owns:
            op.execute(
                f"INSERT INTO sync_log (entity, entity_id) SELECT '{entity}', {column} FROM {table} ORDER BY {column}"
            )
    op.add_column("books", sa.Column("file_sha256", sa.String(length=64), nullable=True))
    op.add_column("books", sa.Column("file_sha256_of", sa.String(length=64), nullable=True))
    op.add_column("auth_challenges", sa.Column("label", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("auth_challenges", "label")
    op.drop_column("books", "file_sha256_of")
    op.drop_column("books", "file_sha256")
    for table, _, _, _ in _SOURCES:
        op.execute(f"DROP TRIGGER {table}_sync_update ON {table}")
        op.execute(f"DROP TRIGGER {table}_sync_write ON {table}")
    op.execute("DROP FUNCTION kodex_sync_log()")
    op.drop_table("sync_log")
