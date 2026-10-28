from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.series import Series


class SeriesReleaseEvent(Base):
    """One known issue/volume of a followed series, from the provider's
    own catalog (Comic Vine only for now — see app/enrichment/comicvine.py's
    list_issue_releases and release_check.py's _sync_release_events; AniList
    exposes no per-chapter listing in this codebase, only a release
    *count*, so MANGA series aren't covered here yet, see that module's
    own note). Backs B5's release calendar/pull-list.

    `status` (unreleased/released/owned) is deliberately NOT a stored
    column — it's computed at read time from store_date vs today and
    whether owned_book_id is set, so it's never stale between the weekly
    sync runs that touch this row and the moment someone actually views
    the calendar.

    A brand new table — inget manuellt ALTER TABLE behövs, bara
    `app/models/__init__.py`s import (create_all() creates it fine).
    """

    __tablename__ = "series_release_events"
    __table_args__ = (UniqueConstraint("series_id", "external_issue_id", name="uq_release_event_series_issue"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True)
    external_issue_id: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    issue_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    store_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    cover_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    # Set once a book already in this series matches this issue by
    # BookMetadata.external_ids.comicvine_issue_id (see
    # release_check.py's _owned_comicvine_issue_ids) — re-computed on
    # every sync, so it self-corrects once the corresponding request is
    # fulfilled and the book actually gets added/matched.
    owned_book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id", ondelete="SET NULL"), nullable=True)
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # User-dismissed from the pull-list view without owning it — e.g. a
    # variant/reprint entry nobody cares to track. Independent of
    # owned_book_id; dismissing never "fakes" ownership.
    dismissed: Mapped[bool] = mapped_column(default=False)

    series: Mapped[Series] = relationship()
    owned_book: Mapped[Book | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SeriesReleaseEvent series_id={self.series_id} issue={self.issue_number!r}>"
