from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import PageFlagReason, PageFlagResolution

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.user import User


class BookPageFlag(Base):
    """A reader-reported "something's wrong with this page" — scanner
    junk, a duplicate scan, a corrupted page (B6's Page Manager). A brand
    new table, sibling to app/models/panel.py's BookPagePanel and for the
    same reason (see that model's own docstring: no Alembic yet, so a new
    table is the only zero-risk schema change).

    A resolved_action=DELETED verdict never rewrites or deletes anything
    in the source archive itself — CBZ/CBR files are treated as immutable
    containers here, same principle kodex/acquire/sorting/comicinfo_writer.py's own
    docstring states for CBR. Instead the page is just excluded from what
    the reader shows (see Book.deleted_page_indices, computed in
    api/routes/books.py's _book_out_detail from resolved DELETED rows) —
    app/scanning/archive.py's (path, mtime)-keyed page cache stays
    completely untouched, keeping this feature's risk isolated to a thin
    read-side filter rather than the hot extraction path.
    """

    __tablename__ = "book_page_flags"
    __table_args__ = (UniqueConstraint("book_id", "page_index", name="uq_page_flag_book_page"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    page_index: Mapped[int] = mapped_column(Integer)

    reason: Mapped[PageFlagReason] = mapped_column(Enum(PageFlagReason, native_enum=False))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    flagged_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    flagged_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    resolved: Mapped[bool] = mapped_column(default=False)
    resolved_action: Mapped[PageFlagResolution | None] = mapped_column(
        Enum(PageFlagResolution, native_enum=False), nullable=True
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    book: Mapped[Book] = relationship()
    flagged_by: Mapped[User | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BookPageFlag book_id={self.book_id} page={self.page_index} resolved={self.resolved}>"
