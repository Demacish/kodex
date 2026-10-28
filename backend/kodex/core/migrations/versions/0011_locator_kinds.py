"""positions say what kind of locator they are

reading_progress and reading_events get locator_kind (kodex.reading.
positions); existing positions get theirs from the book's format and the
position's shape (an unknown shape is kept as "other"), and v1's
"percent:" positions keep only their progression.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("reading_progress", "reading_events")
_KIND = """
    CASE
        WHEN t.position LIKE 'percent:%' THEN 'percent'
        WHEN b.file_format = 'EPUB' AND t.position LIKE 'epubcfi(%' THEN 'cfi'
        WHEN b.file_format = 'EPUB' AND t.position LIKE '/%' THEN 'xpointer'
        WHEN b.file_format = 'PDF' AND t.position ~ '^[0-9]+$' THEN 'pdf'
        WHEN b.file_format NOT IN ('EPUB', 'PDF') AND t.position ~ '^[0-9]+$' THEN 'page'
        ELSE 'other'
    END
"""


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("locator_kind", sa.String(length=16), nullable=True))
        op.execute(
            f"UPDATE {table} AS t SET locator_kind = {_KIND} FROM books AS b "
            "WHERE b.id = t.book_id AND t.position IS NOT NULL"
        )
        op.execute(f"UPDATE {table} SET position = NULL WHERE locator_kind = 'percent'")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"UPDATE {table} SET position = 'percent:' || to_char(progress_percent / 100, 'FM0.000000') "
            "WHERE locator_kind = 'percent' AND position IS NULL"
        )
        op.drop_column(table, "locator_kind")
