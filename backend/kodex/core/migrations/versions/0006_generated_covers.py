"""generated covers

books.cover_key: which source a book's generated covers (three sizes, see
kodex.library.covers) were made from; null until they are made.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("books", sa.Column("cover_key", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("books", "cover_key")
