from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import PanelStatus

if TYPE_CHECKING:
    from app.models.book import Book


class BookPagePanel(Base):
    """One detected panel on one page of one book — powers Guided View
    (see app/panels/detector.py). A brand new table, not a column added to
    the existing `books` table: this app's schema has so far only ever
    grown via new tables under create_all() (see app/main.py's own comment
    on why there's no Alembic yet) — adding a column to `books`, which
    already holds real production data, would be this app's first live
    ALTER TABLE, and an experimental, kill-switchable feature like this one
    shouldn't be what forces that. BookPanelStatus below applies the same
    reasoning to per-book status tracking.
    """

    __tablename__ = "book_page_panels"
    __table_args__ = (UniqueConstraint("book_id", "page_index", "order_index", name="uq_panel_book_page_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    page_index: Mapped[int] = mapped_column(Integer)
    # Canonical top-to-bottom, left-to-right order — reversing left-to-right
    # rows for right-to-left (manga) reading is left to the reader
    # frontend, same as it already reverses spread-pair order (see
    # ImageReader.tsx's orderedSpreadIndexes) — see detector.py's
    # _reading_order.
    order_index: Mapped[int] = mapped_column(Integer)

    # Normalized 0..1 against the page's own dimensions, not pixels — so a
    # cached box stays valid even if the extracted page image is ever
    # re-encoded at a different resolution.
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    w: Mapped[float] = mapped_column(Float)
    h: Mapped[float] = mapped_column(Float)

    book: Mapped[Book] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BookPagePanel book_id={self.book_id} page={self.page_index} order={self.order_index}>"


class BookPanelStatus(Base):
    """One row per book that's had panel detection attempted — lets the API
    answer "does this book support Guided View" with one indexed lookup
    instead of a COUNT(*) over book_page_panels on every book detail
    request, and is also the target of the global guided_view_enabled kill
    switch (see app/panels/service.py) — flipping that setting off makes
    the panels endpoint ignore this table's contents entirely rather than
    needing it cleared out.
    """

    __tablename__ = "book_panel_status"

    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[PanelStatus] = mapped_column(Enum(PanelStatus, native_enum=False), default=PanelStatus.PENDING)
    pages_with_panels: Mapped[int] = mapped_column(Integer, default=0)
    pages_processed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    book: Mapped[Book] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BookPanelStatus book_id={self.book_id} status={self.status}>"
