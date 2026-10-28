from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Enum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import LibraryType, SortingStatus


class SortingItem(Base):
    """One top-level entry (a folder, occasionally a loose file) found
    directly under the intake library's root by a sorting scan — see
    kodex/acquire/sorting/classifier.py for how detected_type/reason get set, and
    kodex/acquire/sorting/api.py for the review-queue + apply flow this backs.
    """

    __tablename__ = "sorting_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Path relative to the intake library's root (settings.libraries_root),
    # e.g. "Batman 001 (2016) (Digital) (Zone-Empire)".
    # Unique so re-running the sorting scan doesn't create duplicate
    # proposals for something already queued/resolved/applied.
    source_path: Mapped[str] = mapped_column(String(2048), unique=True)

    detected_type: Mapped[LibraryType | None] = mapped_column(Enum(LibraryType, native_enum=False), nullable=True)
    detected_reason: Mapped[str] = mapped_column(Text)

    # Set once resolved — either copied straight from detected_type (high-
    # confidence auto-classification) or chosen by an admin in the review
    # queue, including overriding a detected_type they disagree with.
    resolved_type: Mapped[LibraryType | None] = mapped_column(Enum(LibraryType, native_enum=False), nullable=True)

    status: Mapped[SortingStatus] = mapped_column(Enum(SortingStatus, native_enum=False), default=SortingStatus.PENDING)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set if /sorting/apply's move for this item failed (e.g. a destination
    # name collision) — left as RESOLVED so it's retried on the next apply
    # rather than silently stuck, with the reason visible in the meantime.
    apply_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<SortingItem id={self.id} source_path={self.source_path!r} status={self.status}>"
