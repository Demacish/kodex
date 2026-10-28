"""requests for a missing issue: the series it belongs to and its number
(kodex.acquire)

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("series_id", sa.Integer(), nullable=True))
    op.add_column("requests", sa.Column("issue_number", sa.Float(), nullable=True))
    op.create_foreign_key("requests_series_id_fkey", "requests", "series", ["series_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_requests_series_id", "requests", ["series_id"])


def downgrade() -> None:
    op.drop_index("ix_requests_series_id", table_name="requests")
    op.drop_constraint("requests_series_id_fkey", "requests", type_="foreignkey")
    op.drop_column("requests", "issue_number")
    op.drop_column("requests", "series_id")
