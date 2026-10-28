"""content identity

books.content_id, a hash over a book's pages that metadata written into the
file doesn't change, and book_file_hashes, every KOReader document id a
book's file has had. Both are filled in by the scanner: content_id for
every book on the next scan, a file hash whenever a file changes.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("books", sa.Column("content_id", sa.String(length=64), nullable=True))
    op.create_index("ix_books_content_id", "books", ["content_id"])
    op.create_table(
        "book_file_hashes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), server_default="koreader", nullable=False),
        sa.Column("value", sa.String(length=64), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name="book_file_hashes_book_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="book_file_hashes_pkey"),
        sa.UniqueConstraint("kind", "value", name="book_file_hashes_kind_value_key"),
    )
    op.create_index("ix_book_file_hashes_book_id", "book_file_hashes", ["book_id"])
    # The ids books have now are the first ones they had.
    op.execute(
        "INSERT INTO book_file_hashes (book_id, kind, value) SELECT id, 'koreader', content_hash FROM books "
        "WHERE content_hash IS NOT NULL ON CONFLICT (kind, value) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_index("ix_book_file_hashes_book_id", table_name="book_file_hashes")
    op.drop_table("book_file_hashes")
    op.drop_index("ix_books_content_id", table_name="books")
    op.drop_column("books", "content_id")
