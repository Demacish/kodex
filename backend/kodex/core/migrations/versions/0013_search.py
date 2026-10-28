"""search in PostgreSQL

pg_trgm, with trigram indexes on book and series titles, and full-text
indexes on summaries and book text (kodex.discovery.search), in place of
Meilisearch. These are expression indexes, which the schema check leaves
out (their names end in _trgm or _fts, see kodex.core.migrate).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX ix_book_metadata_title_trgm ON book_metadata USING gin (lower(title) gin_trgm_ops)")
    op.execute("CREATE INDEX ix_series_title_trgm ON series USING gin (lower(title) gin_trgm_ops)")
    op.execute(
        "CREATE INDEX ix_book_metadata_summary_fts ON book_metadata "
        "USING gin (to_tsvector('simple', coalesce(summary, '')))"
    )
    op.execute(
        "CREATE INDEX ix_content_index_entries_text_fts ON content_index_entries USING gin (to_tsvector('simple', text))"
    )
    op.create_index("ix_content_index_entries_book_id", "content_index_entries", ["book_id"])


def downgrade() -> None:
    op.drop_index("ix_content_index_entries_book_id", "content_index_entries")
    for name in ("ix_content_index_entries_text_fts", "ix_book_metadata_summary_fts", "ix_series_title_trgm",
                 "ix_book_metadata_title_trgm"):  # fmt: skip
        op.execute(f"DROP INDEX {name}")
