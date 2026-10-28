"""v1 baseline

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """The schema a v1 database got from create_all() as of the last v1
    release, minus the six columns v1 added later through app/migrations.py
    (those, and the drift between hand-migrated databases and the models,
    are 0002). requests and downloads reference each other, so that one
    foreign key is added after both tables exist."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("authentik_sub", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("kindle_email", sa.String(length=255), nullable=True),
        sa.Column("opds_token", sa.String(length=64), nullable=True),
        sa.Column("home_sections", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("users_pkey")),
        sa.UniqueConstraint("authentik_sub", name=op.f("users_authentik_sub_key")),
        sa.UniqueConstraint("opds_token", name=op.f("users_opds_token_key")),
    )
    op.create_table(
        "libraries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column(
            "library_type",
            sa.Enum("COMICS", "EBOOKS", "MANGA", "MIXED", name="librarytype", native_enum=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fulltext_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("libraries_pkey")),
        sa.UniqueConstraint("path", name=op.f("libraries_path_key")),
    )
    op.create_table(
        "scheduler_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_name", sa.String(length=100), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("scheduler_state_pkey")),
        sa.UniqueConstraint("task_name", name=op.f("scheduler_state_task_name_key")),
    )
    op.create_table(
        "sorting_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_path", sa.String(length=2048), nullable=False),
        sa.Column(
            "detected_type",
            sa.Enum("COMICS", "EBOOKS", "MANGA", "MIXED", name="librarytype", native_enum=False),
            nullable=True,
        ),
        sa.Column("detected_reason", sa.Text(), nullable=False),
        sa.Column(
            "resolved_type",
            sa.Enum("COMICS", "EBOOKS", "MANGA", "MIXED", name="librarytype", native_enum=False),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum("PENDING", "RESOLVED", "APPLIED", "SKIPPED", name="sortingstatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("apply_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("sorting_items_pkey")),
        sa.UniqueConstraint("source_path", name=op.f("sorting_items_source_path_key")),
    )
    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "collection_type", sa.Enum("MANUAL", "SMART", name="collectiontype", native_enum=False), nullable=False
        ),
        sa.Column("rule", sa.JSON(), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("cover_image_path", sa.String(length=1024), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=op.f("collections_owner_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("collections_pkey")),
    )
    op.create_table(
        "series",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("library_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("sort_title", sa.String(length=500), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("comicvine_volume_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_following", sa.Boolean(), nullable=False),
        sa.Column("followed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_release_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("known_release_count", sa.Integer(), nullable=True),
        sa.Column("new_release_available", sa.Boolean(), nullable=False),
        sa.Column("metadata_exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["library_id"], ["libraries.id"], name=op.f("series_library_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("series_pkey")),
    )
    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("library_id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=True),
        sa.Column("file_path", sa.String(length=2048), nullable=False),
        sa.Column(
            "file_format",
            sa.Enum("EPUB", "PDF", "CBZ", "CBR", "IMAGE_FOLDER", name="bookformat", native_enum=False),
            nullable=False,
        ),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("file_mtime", sa.Float(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("number", sa.Float(), nullable=True),
        sa.Column(
            "edition_type", sa.Enum("ISSUE", "COLLECTED", name="bookeditiontype", native_enum=False), nullable=False
        ),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["library_id"], ["libraries.id"], name=op.f("books_library_id_fkey"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"], name=op.f("books_series_id_fkey"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("books_pkey")),
        sa.UniqueConstraint("library_id", "file_path", name="uq_book_library_path"),
    )
    op.create_table(
        "requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column(
            "media_type",
            sa.Enum("SERIES", "EBOOK", "MANGA", name="requestmediatype", native_enum=False),
            nullable=False,
        ),
        sa.Column("external_link", sa.String(length=1024), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING", "APPROVED", "FULFILLED", "REJECTED", name="requeststatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("collection_id", sa.Integer(), nullable=True),
        sa.Column("auto_download_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("download_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["collections.id"], name=op.f("requests_collection_id_fkey"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], name=op.f("requests_requested_by_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("requests_pkey")),
    )
    op.create_table(
        "downloads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column(
            "source",
            sa.Enum("PROWLARR", "ANNAS_ARCHIVE", "GETCOMICS", "MANUAL", name="downloadsource", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "client",
            sa.Enum("QBITTORRENT", "SABNZBD", "DIRECT_HTTP", name="downloadclienttype", native_enum=False),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED", "DOWNLOADING", "COMPLETED", "FAILED", "NEEDS_REVIEW", name="downloadstatus", native_enum=False
            ),
            nullable=False,
        ),
        sa.Column("progress", sa.Float(), nullable=True),
        sa.Column("save_path", sa.String(length=2048), nullable=True),
        sa.Column("library_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], name=op.f("downloads_created_by_user_id_fkey"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["library_id"], ["libraries.id"], name=op.f("downloads_library_id_fkey"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["requests.id"], name=op.f("downloads_request_id_fkey"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("downloads_pkey")),
    )
    op.create_table(
        "ai_recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("author", sa.String(length=500), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "media_type_guess",
            sa.Enum("SERIES", "EBOOK", "MANGA", name="requestmediatype", native_enum=False),
            nullable=True,
        ),
        sa.Column("cover_url", sa.String(length=1024), nullable=True),
        sa.Column(
            "status",
            sa.Enum("SUGGESTED", "REQUESTED", "DISMISSED", name="aisuggestionstatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"], ["requests.id"], name=op.f("ai_recommendations_request_id_fkey"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("ai_recommendations_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("ai_recommendations_pkey")),
    )
    op.create_index(op.f("ix_ai_recommendations_user_id"), "ai_recommendations", ["user_id"], unique=False)
    op.create_table(
        "kosync_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("document", sa.String(length=64), nullable=False),
        sa.Column("progress", sa.String(length=1024), nullable=True),
        sa.Column("percentage", sa.Float(), nullable=False),
        sa.Column("device", sa.String(length=255), nullable=True),
        sa.Column("device_id", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("kosync_progress_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("kosync_progress_pkey")),
        sa.UniqueConstraint("user_id", "document", name="uq_kosync_user_document"),
    )
    op.create_index(op.f("ix_kosync_progress_user_id"), "kosync_progress", ["user_id"], unique=False)
    op.create_table(
        "story_arcs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comicvine_id", sa.Integer(), nullable=True),
        sa.Column("metron_id", sa.Integer(), nullable=True),
        sa.Column("cbl_path", sa.String(length=1024), nullable=True),
        sa.Column("locg_event_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("collection_id", sa.Integer(), nullable=True),
        sa.Column("roster_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["collections.id"], name=op.f("story_arcs_collection_id_fkey"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("story_arcs_pkey")),
        sa.UniqueConstraint("cbl_path", name=op.f("story_arcs_cbl_path_key")),
        sa.UniqueConstraint("comicvine_id", name=op.f("story_arcs_comicvine_id_key")),
        sa.UniqueConstraint("locg_event_id", name=op.f("story_arcs_locg_event_id_key")),
        sa.UniqueConstraint("metron_id", name=op.f("story_arcs_metron_id_key")),
    )
    op.create_table(
        "book_metadata",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("sort_title", sa.String(length=500), nullable=False),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("genres", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("story_arcs", sa.JSON(), nullable=False),
        sa.Column("story_arc_numbers", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("publisher", sa.String(length=255), nullable=True),
        sa.Column("published_year", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("isbn", sa.String(length=32), nullable=True),
        sa.Column("cover_path", sa.String(length=1024), nullable=True),
        sa.Column(
            "source",
            sa.Enum("EMBEDDED", "ENRICHED", "MANUAL", name="metadatasource", native_enum=False),
            nullable=False,
        ),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("external_ids", sa.JSON(), nullable=True),
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("book_metadata_book_id_fkey"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("book_metadata_pkey")),
        sa.UniqueConstraint("book_id", name=op.f("book_metadata_book_id_key")),
    )
    op.create_table(
        "book_page_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column(
            "reason",
            sa.Enum("BLANK", "DUPLICATE", "CORRUPT", "OTHER", name="pageflagreason", native_enum=False),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("flagged_by_user_id", sa.Integer(), nullable=True),
        sa.Column("flagged_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column(
            "resolved_action", sa.Enum("DELETED", "KEPT", name="pageflagresolution", native_enum=False), nullable=True
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("book_page_flags_book_id_fkey"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["flagged_by_user_id"],
            ["users.id"],
            name=op.f("book_page_flags_flagged_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("book_page_flags_pkey")),
        sa.UniqueConstraint("book_id", "page_index", name="uq_page_flag_book_page"),
    )
    op.create_index(op.f("ix_book_page_flags_book_id"), "book_page_flags", ["book_id"], unique=False)
    op.create_table(
        "book_page_panels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("w", sa.Float(), nullable=False),
        sa.Column("h", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("book_page_panels_book_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("book_page_panels_pkey")),
        sa.UniqueConstraint("book_id", "page_index", "order_index", name="uq_panel_book_page_order"),
    )
    op.create_index(op.f("ix_book_page_panels_book_id"), "book_page_panels", ["book_id"], unique=False)
    op.create_table(
        "book_panel_status",
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "DONE", "FAILED", "UNSUPPORTED", name="panelstatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("pages_with_panels", sa.Integer(), nullable=False),
        sa.Column("pages_processed", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=1024), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("book_panel_status_book_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("book_id", name=op.f("book_panel_status_pkey")),
    )
    op.create_table(
        "collection_books",
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("collection_books_book_id_fkey"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["collections.id"], name=op.f("collection_books_collection_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("collection_id", "book_id", name=op.f("collection_books_pkey")),
    )
    op.create_table(
        "content_index_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.String(length=512), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("content_index_entries_book_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("content_index_entries_pkey")),
    )
    op.create_table(
        "reading_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.String(length=512), nullable=True),
        sa.Column("progress_percent", sa.Float(), nullable=False),
        sa.Column("is_finished", sa.Boolean(), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_read_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("reading_progress_book_id_fkey"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("reading_progress_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("reading_progress_pkey")),
        sa.UniqueConstraint("user_id", "book_id", name="uq_progress_user_book"),
    )
    op.create_table(
        "series_release_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("external_issue_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("issue_number", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("store_date", sa.Date(), nullable=True),
        sa.Column("cover_date", sa.Date(), nullable=True),
        sa.Column("owned_book_id", sa.Integer(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("dismissed", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owned_book_id"], ["books.id"], name=op.f("series_release_events_owned_book_id_fkey"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["series_id"], ["series.id"], name=op.f("series_release_events_series_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("series_release_events_pkey")),
        sa.UniqueConstraint("series_id", "external_issue_id", name="uq_release_event_series_issue"),
    )
    op.create_index(op.f("ix_series_release_events_series_id"), "series_release_events", ["series_id"], unique=False)
    op.create_table(
        "story_arc_issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("story_arc_id", sa.Integer(), nullable=False),
        sa.Column("comicvine_issue_id", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=500), nullable=False),
        sa.Column("cover_url", sa.String(length=1024), nullable=True),
        sa.Column("site_detail_url", sa.String(length=1024), nullable=True),
        sa.Column("book_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("story_arc_issues_book_id_fkey"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["story_arc_id"], ["story_arcs.id"], name=op.f("story_arc_issues_story_arc_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("story_arc_issues_pkey")),
    )
    op.create_foreign_key(
        op.f("requests_download_id_fkey"), "requests", "downloads", ["download_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("requests_download_id_fkey"), "requests", type_="foreignkey")
    op.drop_table("story_arc_issues")
    op.drop_index(op.f("ix_series_release_events_series_id"), table_name="series_release_events")
    op.drop_table("series_release_events")
    op.drop_table("reading_progress")
    op.drop_table("content_index_entries")
    op.drop_table("collection_books")
    op.drop_table("book_panel_status")
    op.drop_index(op.f("ix_book_page_panels_book_id"), table_name="book_page_panels")
    op.drop_table("book_page_panels")
    op.drop_index(op.f("ix_book_page_flags_book_id"), table_name="book_page_flags")
    op.drop_table("book_page_flags")
    op.drop_table("book_metadata")
    op.drop_table("story_arcs")
    op.drop_index(op.f("ix_kosync_progress_user_id"), table_name="kosync_progress")
    op.drop_table("kosync_progress")
    op.drop_index(op.f("ix_ai_recommendations_user_id"), table_name="ai_recommendations")
    op.drop_table("ai_recommendations")
    op.drop_table("downloads")
    op.drop_table("requests")
    op.drop_table("books")
    op.drop_table("series")
    op.drop_table("collections")
    op.drop_table("sorting_items")
    op.drop_table("scheduler_state")
    op.drop_table("libraries")
    op.drop_table("users")
