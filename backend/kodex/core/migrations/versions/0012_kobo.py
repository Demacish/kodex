"""Kobo sync

kobo_devices: a Kobo e-reader syncing through a Kobo key, and the
collection it gets; kobo_books: which books it was given (kodex.reading.
kobo).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kobo_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("api_key_id", sa.Integer(), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["api_key_id"], ["api_keys.id"], name="kobo_devices_api_key_id_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["collections.id"], name="kobo_devices_collection_id_fkey", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="kobo_devices_pkey"),
        sa.UniqueConstraint("api_key_id", name="kobo_devices_api_key_id_key"),
    )
    op.create_table(
        "kobo_books",
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name="kobo_books_book_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["device_id"], ["kobo_devices.id"], name="kobo_books_device_id_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("device_id", "book_id", name="kobo_books_pkey"),
    )


def downgrade() -> None:
    op.drop_table("kobo_books")
    op.drop_table("kobo_devices")
