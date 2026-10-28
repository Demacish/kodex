"""What the OPDS feeds list, in pages: libraries, a library's series and
loose books, a series' books, the newest books, what the user is reading,
followed series and a title search. Both feed formats (``atom``, ``v2``)
read from here."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, selectinload

from app.models.book import Book
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.reading_progress import ReadingProgress
from app.models.series import Series

PAGE_SIZE = 50
# app.models.book.visible_books: a file that went missing isn't listed.
_VISIBLE = Book.missing_since.is_(None)


@dataclass(frozen=True)
class Page[T]:
    items: Sequence[T]
    number: int  # 1-based
    total: int
    size: int = PAGE_SIZE

    @property
    def last(self) -> int:
        return max(1, -(-self.total // self.size))


def _page[T](db: Session, query: Select[T], number: int, size: int = PAGE_SIZE) -> Page[T]:
    number = max(number, 1)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    items = db.scalars(query.limit(size).offset((number - 1) * size)).all()
    return Page(items, number, int(total), size)


def _books() -> Select[Book]:
    return select(Book).where(_VISIBLE).options(selectinload(Book.book_metadata), selectinload(Book.series))


def libraries(db: Session) -> Sequence[Library]:
    return db.scalars(select(Library).order_by(Library.name)).all()


def library(db: Session, library_id: int) -> Library | None:
    return db.get(Library, library_id)


def series_of(db: Session, library_id: int, number: int) -> Page[Series]:
    has_books = Series.books.any(_VISIBLE)
    query = select(Series).where(Series.library_id == library_id, has_books).order_by(Series.sort_title, Series.id)
    return _page(db, query, number)


def loose_books(db: Session, library_id: int) -> Sequence[Book]:
    query = _books().where(Book.library_id == library_id, Book.series_id.is_(None)).order_by(Book.file_path)
    return db.scalars(query.limit(500)).all()


def series(db: Session, series_id: int) -> Series | None:
    return db.get(Series, series_id)


def books_of(db: Session, series_id: int, number: int) -> Page[Book]:
    query = _books().where(Book.series_id == series_id).order_by(Book.number.nulls_last(), Book.file_path)
    return _page(db, query, number)


def latest(db: Session, number: int) -> Page[Book]:
    return _page(db, _books().order_by(Book.added_at.desc(), Book.id.desc()), number)


def reading(db: Session, user_id: int, number: int) -> Page[Book]:
    started = select(ReadingProgress.book_id).where(ReadingProgress.user_id == user_id,
                                                    ReadingProgress.is_finished.is_(False),
                                                    ReadingProgress.progress_percent > 0)  # fmt: skip
    newest = (select(ReadingProgress.last_read_at).where(ReadingProgress.user_id == user_id,
                                                         ReadingProgress.book_id == Book.id)
              .scalar_subquery())  # fmt: skip
    query = _books().where(Book.id.in_(started)).order_by(newest.desc())
    return _page(db, query, number)


def followed(db: Session, number: int) -> Page[Series]:
    query = select(Series).where(Series.is_following.is_(True)).order_by(Series.sort_title, Series.id)
    return _page(db, query, number)


def search(db: Session, text: str, number: int) -> Page[Book]:
    """Books whose title, series or author contains the words."""
    words = [w for w in text.split() if w][:8]
    query = (
        _books().outerjoin(BookMetadata, BookMetadata.book_id == Book.id).outerjoin(Series, Series.id == Book.series_id)
    )
    for word in words:
        like = f"%{word}%"
        query = query.where(or_(BookMetadata.title.ilike(like), Series.title.ilike(like),
                                cast(cast(BookMetadata.authors, JSONB), String).ilike(like)))  # fmt: skip
    return _page(db, query.order_by(Series.sort_title.nulls_last(), Book.number.nulls_last(), Book.id), number)


def progress(db: Session, user_id: int, book_ids: Sequence[int]) -> dict[int, ReadingProgress]:
    if not book_ids:
        return {}
    rows = db.scalars(select(ReadingProgress).where(ReadingProgress.user_id == user_id,
                                                    ReadingProgress.book_id.in_(book_ids)))  # fmt: skip
    return {row.book_id: row for row in rows}


def first_book(db: Session, series_ids: Sequence[int]) -> dict[int, int]:
    """The first book of each series, for the series' cover."""
    if not series_ids:
        return {}
    rows = db.execute(
        select(Book.series_id, Book.id).where(Book.series_id.in_(series_ids), _VISIBLE)
        .distinct(Book.series_id).order_by(Book.series_id, Book.number.nulls_last(), Book.file_path)
    ).all()  # fmt: skip
    return {int(series_id): int(book_id) for series_id, book_id in rows if series_id is not None}
