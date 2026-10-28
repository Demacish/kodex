"""duplicates and write-back

libraries.read_only and libraries.write_back (both off), and
books.cover_phash, filled in when covers are made, for finding the same
book in two different files.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("libraries", sa.Column("read_only", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("libraries", sa.Column("write_back", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("books", sa.Column("cover_phash", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("books", "cover_phash")
    op.drop_column("libraries", "write_back")
    op.drop_column("libraries", "read_only")
