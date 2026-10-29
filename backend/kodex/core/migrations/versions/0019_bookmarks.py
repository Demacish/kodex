"""bookmarks: places in a book a user wants to find again, on any device
(kodex.reading.bookmarks)

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bookmarks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.String(length=512), nullable=False),
        sa.Column("locator_kind", sa.String(length=16), nullable=False),
        sa.Column("progress_percent", sa.Float(), nullable=False),
        sa.Column("chapter", sa.String(length=255), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name="bookmarks_book_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="bookmarks_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="bookmarks_pkey"),
    )
    op.create_index("ix_bookmarks_user_id_book_id", "bookmarks", ["user_id", "book_id"])


def downgrade() -> None:
    op.drop_index("ix_bookmarks_user_id_book_id", table_name="bookmarks")
    op.drop_table("bookmarks")
