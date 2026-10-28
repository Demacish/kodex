"""Delta sync for apps that keep the catalog offline (the Android app):
``GET /sync/changes?since=<cursor>`` answers with what changed after the
cursor, a page at a time, deletions as tombstones, and the next cursor.

Changes are written by triggers in the database (migration 0014), so every
write counts, whichever code made it: each row of ``sync_log`` says which
library, series, book or collection changed (or went), in the order of a
monotonic sequence. A client that was offline for a week asks with its
last cursor and gets only what changed since, whatever the clock said.
A book whose file is missing is a tombstone too, until it comes back.

The user's reading positions come along with their own cursor, the
reading journal's (an event id), so a position read elsewhere reaches the
app on the same request."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models.book import Book
from app.models.collection import Collection, collection_books
from app.models.enums import CollectionType
from app.models.library import Library
from app.models.reading_progress import ReadingProgress
from app.models.series import Series
from app.models.user import User
from app.schemas.book import BookOut
from app.schemas.library import LibraryOut
from app.schemas.reading_progress import ReadingProgressOut
from app.schemas.series import SeriesOut
from kodex.core.sync_log import SyncLog
from kodex.reading.models import ReadingEvent

PAGE = 500
ENTITIES = ("library", "series", "book", "collection")
router = APIRouter(tags=["sync"])


class SyncCollectionOut(BaseModel):
    id: int
    name: str
    collection_type: CollectionType
    book_ids: list[int]


class SyncDeletedOut(BaseModel):
    libraries: list[int] = []
    series: list[int] = []
    books: list[int] = []
    collections: list[int] = []


class SyncChangesOut(BaseModel):
    cursor: int
    more: bool
    reset: bool = False
    libraries: list[LibraryOut] = []
    series: list[SeriesOut] = []
    books: list[BookOut] = []
    collections: list[SyncCollectionOut] = []
    deleted: SyncDeletedOut = SyncDeletedOut()
    progress_cursor: int
    progress_more: bool = False
    progress: list[ReadingProgressOut] = []


def _latest(db: Session, since: int, limit: int) -> list[tuple[str, int, bool, int]]:
    """The newest log row per entity changed after ``since``, oldest first."""
    rows = db.execute(
        text(
            "SELECT entity, entity_id, deleted, seq FROM ("
            " SELECT DISTINCT ON (entity, entity_id) entity, entity_id, deleted, seq FROM sync_log"
            " WHERE seq > :since ORDER BY entity, entity_id, seq DESC) AS latest"
            " ORDER BY seq LIMIT :limit"
        ),
        {"since": since, "limit": limit},
    ).all()
    return [(r.entity, int(r.entity_id), bool(r.deleted), int(r.seq)) for r in rows]


def changes(db: Session, user: User, since: int, progress_since: int, limit: int = PAGE) -> SyncChangesOut:
    head = int(db.scalar(select(func.coalesce(func.max(SyncLog.seq), 0))) or 0)
    if since > head:  # a cursor from before the database was restored
        return SyncChangesOut(cursor=0, more=True, reset=True, progress_cursor=0)
    rows = _latest(db, since, limit + 1)
    more = len(rows) > limit
    rows = rows[:limit]
    cursor = rows[-1][3] if rows else head
    wanted: dict[str, set[int]] = defaultdict(set)
    gone: dict[str, set[int]] = defaultdict(set)
    for entity, entity_id, deleted, _ in rows:
        (gone if deleted else wanted)[entity].add(entity_id)

    out = SyncChangesOut(cursor=cursor, more=more, progress_cursor=progress_since)
    libraries = db.scalars(select(Library).where(Library.id.in_(wanted["library"]))).all()
    out.libraries = [LibraryOut.model_validate(lib) for lib in libraries]
    gone["library"] |= wanted["library"] - {lib.id for lib in libraries}

    series = db.scalars(select(Series).where(Series.id.in_(wanted["series"]))).all()
    counts = dict(db.execute(select(Book.series_id, func.count()).where(Book.series_id.in_([s.id for s in series]),
                                                                        Book.missing_since.is_(None))
                             .group_by(Book.series_id)).all())  # fmt: skip
    out.series = [
        SeriesOut.model_validate(s).model_copy(update={"book_count": int(counts.get(s.id, 0))}) for s in series
    ]
    gone["series"] |= wanted["series"] - {s.id for s in series}

    books = db.scalars(select(Book).where(Book.id.in_(wanted["book"])).options(selectinload(Book.book_metadata))).all()
    out.books = [BookOut.model_validate(b) for b in books if b.missing_since is None]
    gone["book"] |= wanted["book"] - {b.id for b in out.books}

    visible = or_(Collection.owner_user_id.is_(None), Collection.owner_user_id == user.id)
    collections = db.scalars(select(Collection).where(Collection.id.in_(wanted["collection"]), visible)).all()
    members: dict[int, list[int]] = defaultdict(list)
    for collection_id, book_id in db.execute(
        select(collection_books.c.collection_id, collection_books.c.book_id)
        .where(collection_books.c.collection_id.in_([c.id for c in collections]))
        .order_by(collection_books.c.position.nulls_last(), collection_books.c.book_id)
    ):  # fmt: skip
        members[collection_id].append(book_id)
    out.collections = [SyncCollectionOut(id=c.id, name=c.name, collection_type=c.collection_type,
                                         book_ids=members[c.id]) for c in collections]  # fmt: skip
    gone["collection"] |= wanted["collection"] - {c.id for c in collections}
    out.deleted = SyncDeletedOut(libraries=sorted(gone["library"]), series=sorted(gone["series"]),
                                 books=sorted(gone["book"]), collections=sorted(gone["collection"]))  # fmt: skip

    changed = (select(ReadingEvent.book_id, func.max(ReadingEvent.id).label("last"))
               .where(ReadingEvent.user_id == user.id, ReadingEvent.id > progress_since)
               .group_by(ReadingEvent.book_id).subquery())  # fmt: skip
    found = db.execute(select(ReadingProgress, changed.c.last).join(changed, changed.c.book_id == ReadingProgress.book_id)
                       .where(ReadingProgress.user_id == user.id).order_by(changed.c.last).limit(limit + 1)).all()  # fmt: skip
    out.progress_more = len(found) > limit
    found = found[:limit]
    out.progress = [ReadingProgressOut.model_validate(p) for p, _ in found]
    if found:
        out.progress_cursor = int(found[-1][1])
    return out


@router.get("/sync/changes", response_model=SyncChangesOut)
def sync_changes(since: int = Query(0, ge=0), progress_since: int = Query(0, ge=0),
                 limit: int = Query(PAGE, ge=1, le=2000), db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)) -> SyncChangesOut:  # fmt: skip
    """What changed after ``since`` (start with 0), a page at a time: ask
    again with ``cursor`` while ``more`` is true. ``reset`` means the
    server's history doesn't go back to the cursor: start over from 0.
    Positions come after ``progress_since`` with their own cursor."""
    return changes(db, user, since, progress_since, limit)


def compact(db: Session) -> int:
    """Keeps only each entity's newest log row; returns how many went."""
    result = db.execute(
        text(
            "DELETE FROM sync_log AS old USING sync_log AS newer"
            " WHERE old.entity = newer.entity AND old.entity_id = newer.entity_id AND old.seq < newer.seq"
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)
