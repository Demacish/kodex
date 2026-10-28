"""Putting books in series: placing a new book by its key, proposing a
regroup when an existing book's key changes, and the manual actions
(move, merge, split) that the review queue and the admin API use.

Nothing here moves a book silently. A new book is placed by its key; a
book already in a series only moves when someone accepts a proposal or
moves it by hand, and a book moved by hand is locked to its series.
"""

from __future__ import annotations

import copy
import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.library import Library
from app.models.series import Series
from kodex.matching.group import SeriesKey
from kodex.matching.models import MatchReview, SeriesAlias, SeriesExternalId


def find_series(db: Session, library_id: int, key: SeriesKey) -> Series | None:
    return db.scalars(select(Series).where(Series.library_id == library_id, Series.group_key == key.key)).first()


def fill_from_key(series: Series, key: SeriesKey) -> None:
    series.group_key = key.key
    series.norm_title = series.norm_title or key.norm_title
    series.format_family = key.format_family
    if series.start_year is None:
        series.start_year = key.start_year


def place_book(db: Session, library: Library, book: Book, key: SeriesKey | None) -> Series | None:
    """The series a new book goes into, created if needed."""
    if key is None:
        return None
    series = find_series(db, library.id, key)
    if series is None and key.folder is not None and key.run.startswith("folder:"):
        # A v1 series (grouped by folder, no key yet) is adopted as it is.
        series = db.scalars(
            select(Series).where(Series.library_id == library.id, Series.path == key.folder, Series.group_key.is_(None))
        ).first()
    if series is None:
        series = Series(library_id=library.id, title=key.title, sort_title=key.title, path=key.folder or key.title)
        db.add(series)
    fill_from_key(series, key)
    db.flush()
    return series


def check_grouping(db: Session, library: Library, book: Book, key: SeriesKey | None) -> None:
    """A book already in a series whose key no longer matches it: the move
    is proposed in the review queue, never made here. A v1 series without
    a key is given the book's key when it is the same folder."""
    current = db.get(Series, book.series_id) if book.series_id is not None else None
    if key is None or current is None or book.series_locked or current.group_key == key.key:
        return
    if current.group_key is None:
        same_folder = key.folder is not None and current.path == key.folder and key.run.startswith("folder:")
        if same_folder or (find_series(db, library.id, key) is None and _only_book(db, current, book)):
            fill_from_key(current, key)
            db.flush()
            return
    propose_regroup(db, library, book, current, key)


def _only_book(db: Session, series: Series, book: Book) -> bool:
    count = db.scalar(select(func.count()).select_from(Book).where(Book.series_id == series.id))
    return count == 1 and book.series_id == series.id


def propose_regroup(db: Session, library: Library, book: Book, current: Series, key: SeriesKey) -> MatchReview:
    """Records that ``book`` now belongs under ``key`` rather than in
    ``current``. Proposals for the same series are gathered in one open
    review, grouped by target key."""
    review = db.scalars(
        select(MatchReview).where(
            MatchReview.kind == "regroup", MatchReview.series_id == current.id, MatchReview.status == "open"
        )
    ).first()
    if review is None:
        review = MatchReview(
            kind="regroup", library_id=library.id, series_id=current.id, title=current.title, parsed={"moves": {}}
        )
        db.add(review)
    # A deep copy: JSON columns only notice reassignment, so changing the
    # stored structure in place would silently lose these books.
    moves: dict[str, Any] = copy.deepcopy((review.parsed or {}).get("moves", {}))
    target = find_series(db, library.id, key)
    move = moves.get(key.key) or {"title": key.title, "key": key.key, "book_ids": []}
    move["target_series_id"] = target.id if target else None
    if book.id not in move["book_ids"]:
        move["book_ids"] = [*move["book_ids"], book.id]
    moves[key.key] = move
    review.parsed = {"moves": moves, "key": {"title": key.title, "run": key.run, "family": key.format_family}}
    review.book_count = sum(len(m["book_ids"]) for m in moves.values())
    db.flush()
    return review


def accept_regroup(db: Session, review: MatchReview, user_id: int | None = None) -> None:
    """Moves every proposed book to the series of its new key."""
    library = db.get(Library, review.library_id)
    assert library is not None
    for move in (review.parsed or {}).get("moves", {}).values():
        title, (norm_title, run, family) = move["title"], move["key"].split("|", 2)
        key = SeriesKey(title, norm_title, run, family, int(run) if run.isdigit() else None, None)
        target = find_series(db, library.id, key)
        if target is None:
            target = Series(library_id=library.id, title=title, sort_title=title, path=title)
            db.add(target)
            fill_from_key(target, key)
            db.flush()
        move_books(db, move["book_ids"], target, lock=False)
    _close(review, "resolved", {"action": "accept"}, user_id)


def reject_regroup(db: Session, review: MatchReview, user_id: int | None = None) -> None:
    """Keeps the books where they are, and stops asking."""
    for move in (review.parsed or {}).get("moves", {}).values():
        for book in db.scalars(select(Book).where(Book.id.in_(move["book_ids"]))):
            book.series_locked = True
    _close(review, "dismissed", {"action": "reject"}, user_id)


def _close(review: MatchReview, status: str, decision: dict[str, Any], user_id: int | None) -> None:
    review.status = status
    review.decision = decision
    review.decided_by_user_id = user_id
    review.decided_at = dt.datetime.now(dt.UTC)


def move_books(db: Session, book_ids: list[int], target: Series, *, lock: bool = True) -> None:
    """Moves books into ``target``; a series left empty is removed (its
    follow flag passes on to the target)."""
    sources: set[int] = set()
    for book in db.scalars(select(Book).where(Book.id.in_(book_ids))):
        if book.series_id is not None and book.series_id != target.id:
            sources.add(book.series_id)
        book.series_id = target.id
        book.series_locked = book.series_locked or lock
    db.flush()
    for source_id in sources:
        source = db.get(Series, source_id)
        if source is not None:
            _delete_if_empty(db, source, heir=target)


def merge_series(db: Session, target: Series, sources: list[Series]) -> None:
    """Moves every book, external id and the follow flag of ``sources``
    into ``target`` and removes them."""
    for source in sources:
        if source.id == target.id:
            continue
        book_ids = list(db.scalars(select(Book.id).where(Book.series_id == source.id)))
        known = {
            (e.provider, e.external_id)
            for e in db.scalars(select(SeriesExternalId).where(SeriesExternalId.series_id == target.id))
        }
        for external in db.scalars(select(SeriesExternalId).where(SeriesExternalId.series_id == source.id)):
            if (external.provider, external.external_id) not in known:
                db.add(SeriesExternalId(series_id=target.id, provider=external.provider, external_id=external.external_id,
                                        is_primary=False, source=external.source))  # fmt: skip
        move_books(db, book_ids, target, lock=True)
        if db.get(Series, source.id) is not None:
            _delete_if_empty(db, source, heir=target)


def split_series(db: Session, series: Series, book_ids: list[int], title: str) -> Series:
    """Moves ``book_ids`` out of ``series`` into a new series named
    ``title`` (for a folder that holds several runs)."""
    new = Series(library_id=series.library_id, title=title, sort_title=title, path=series.path,
                 format_family=series.format_family)  # fmt: skip
    db.add(new)
    db.flush()
    move_books(db, book_ids, new, lock=True)
    return new


def _delete_if_empty(db: Session, series: Series, *, heir: Series) -> None:
    remaining = db.scalar(select(func.count()).select_from(Book).where(Book.series_id == series.id))
    if remaining:
        return
    if series.is_following and not heir.is_following:
        heir.is_following = True
        heir.followed_at = series.followed_at
    db.delete(series)
    db.flush()


def remember_alias(
    db: Session, series: Series, provider: str, external_id: str, *, positive: bool = True
) -> SeriesAlias | None:
    """Stores a decision as an alias: this title (and year) is, or is not,
    that provider id. Returns the alias (new or already there)."""
    if not series.norm_title:
        return None
    polarity = "positive" if positive else "negative"
    alias = db.scalars(
        select(SeriesAlias).where(
            SeriesAlias.norm_title == series.norm_title,
            SeriesAlias.year.is_(None) if series.start_year is None else SeriesAlias.year == series.start_year,
            SeriesAlias.library_id == series.library_id,
            SeriesAlias.provider == provider,
            SeriesAlias.external_id == external_id,
            SeriesAlias.polarity == polarity,
        )
    ).first()
    if alias is None:
        alias = SeriesAlias(norm_title=series.norm_title, year=series.start_year, library_id=series.library_id,
                            provider=provider, external_id=external_id, polarity=polarity, source="manual")  # fmt: skip
        db.add(alias)
        db.flush()
    return alias
