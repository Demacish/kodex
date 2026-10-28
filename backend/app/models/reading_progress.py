from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.user import User


class ReadingProgress(Base):
    """Per-user, per-book reading position — the source of truth for resuming
    on any device, and for the "Fortsätter läsa" shelf on the start page.
    """

    __tablename__ = "reading_progress"
    __table_args__ = (UniqueConstraint("user_id", "book_id", name="uq_progress_user_book"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))

    # The reader's own locator and what kind it is (a page index, a PDF
    # page, an EPUB CFI, KOReader's XPointer, a Kobo location; see
    # kodex.reading.positions); a reader that can't use the kind opens at
    # progress_percent.
    position: Mapped[str | None] = mapped_column(String(512), nullable=True)
    locator_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    progress_percent: Mapped[float] = mapped_column(Float, default=0.0)
    is_finished: Mapped[bool] = mapped_column(Boolean, default=False)

    # EPUB only: the reader's current table-of-contents label, saved
    # alongside the CFI in `position` (see ReadingProgressIn.chapter).
    # Added after this table already existed in production — see
    # app/migrations.py, which adds the column on startup.
    chapter: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Set when the user removes this book from the "Fortsätter läsa" shelf.
    # Cleared automatically the next time progress is saved for this book, so
    # resuming naturally brings it back — see the architecture plan.
    dismissed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The device whose report this position is (kodex.reading.journal), so
    # a reader can tell a position from another device from its own.
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    last_read_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship()
    book: Mapped[Book] = relationship(back_populates="reading_progress")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ReadingProgress user_id={self.user_id} book_id={self.book_id} {self.progress_percent:.0f}%>"
