"""v1 late columns and drift

The six columns v1 added on startup through app/migrations.py, plus the
places where hand-migrated v1 databases differ from what create_all()
produces: books.edition_type was added by hand as an unbounded VARCHAR
with a default, requests.download_id lost its ON DELETE SET NULL, and the
content_hash index was never created. Every statement is idempotent, so
any v1 database ends up identical to a fresh one.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LATE_COLUMNS = [
    ("reading_progress", "chapter", "VARCHAR(255)"),
    ("books", "missing_since", "TIMESTAMP WITH TIME ZONE"),
    ("books", "keep_visible_when_missing", "BOOLEAN"),
    ("books", "content_hash", "VARCHAR(32)"),
    ("users", "ntfy_topic", "VARCHAR(64)"),
    ("books", "page_dimensions", "JSON"),
]


def upgrade() -> None:
    for table, column, sql_type in _LATE_COLUMNS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {sql_type}")
    op.execute("CREATE INDEX IF NOT EXISTS ix_books_content_hash ON books (content_hash)")
    op.execute(
        "ALTER TABLE books ALTER COLUMN edition_type TYPE VARCHAR(9), ALTER COLUMN edition_type SET DEFAULT 'ISSUE'"
    )
    op.execute("ALTER TABLE requests DROP CONSTRAINT IF EXISTS requests_download_id_fkey")
    op.execute(
        "ALTER TABLE requests ADD CONSTRAINT requests_download_id_fkey "
        "FOREIGN KEY (download_id) REFERENCES downloads (id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE books ALTER COLUMN edition_type DROP DEFAULT")
    op.execute("DROP INDEX IF EXISTS ix_books_content_hash")
    for table, column, _ in reversed(_LATE_COLUMNS):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
