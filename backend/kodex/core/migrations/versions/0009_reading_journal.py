"""reading journal

Every position a device reports goes to reading_events (kodex.reading);
reading_progress keeps the current one and which device it came from.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reading_progress", sa.Column("device_id", sa.String(length=64), nullable=True))
    op.add_column("reading_progress", sa.Column("device_name", sa.String(length=100), nullable=True))
    op.create_table(
        "reading_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("device_name", sa.String(length=100), nullable=True),
        sa.Column("client_seq", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("position", sa.String(length=512), nullable=True),
        sa.Column("progress_percent", sa.Float(), nullable=False),
        sa.Column("chapter", sa.String(length=255), nullable=True),
        sa.Column("client_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name="reading_events_book_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="reading_events_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="reading_events_pkey"),
    )
    op.create_index("ix_reading_events_book_id", "reading_events", ["book_id"])
    op.create_index(
        "ix_reading_events_user_id_book_id_received_at", "reading_events", ["user_id", "book_id", "received_at"]
    )
    # The current positions become the journal's first entries.
    op.execute(
        "INSERT INTO reading_events (user_id, book_id, device_id, kind, position, progress_percent, chapter, received_at) "
        "SELECT user_id, book_id, 'kodex', CASE WHEN is_finished THEN 'finished' ELSE 'progress' END, position, "
        "progress_percent, chapter, last_read_at FROM reading_progress"
    )


def downgrade() -> None:
    op.drop_table("reading_events")
    op.drop_column("reading_progress", "device_name")
    op.drop_column("reading_progress", "device_id")
