"""trackers: a user's accounts at MangaUpdates, Kitsu, AniList and
MyAnimeList, and the series linked to entries there (kodex.reading.trackers)

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tracker_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("service", sa.String(length=16), nullable=False),
        sa.Column("remote_user_id", sa.String(length=64), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="tracker_accounts_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="tracker_accounts_pkey"),
        sa.UniqueConstraint("user_id", "service", name="tracker_accounts_user_id_service_key"),
    )
    op.create_index("ix_tracker_accounts_user_id", "tracker_accounts", ["user_id"])
    op.create_table(
        "tracker_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("service", sa.String(length=16), nullable=False),
        sa.Column("remote_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("unit", sa.String(length=8), nullable=False),
        sa.Column("sent_progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="tracker_links_user_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"], name="tracker_links_series_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="tracker_links_pkey"),
        sa.UniqueConstraint("user_id", "series_id", "service", name="tracker_links_user_id_series_id_service_key"),
    )
    op.create_index("ix_tracker_links_user_id", "tracker_links", ["user_id"])
    op.create_index("ix_tracker_links_series_id", "tracker_links", ["series_id"])


def downgrade() -> None:
    op.drop_table("tracker_links")
    op.drop_table("tracker_accounts")
