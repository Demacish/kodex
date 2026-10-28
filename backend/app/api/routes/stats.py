"""Library statistics, for a homepage-dashboard widget (with config.py's
stats_api_key as a fixed header key, since a widget has no user session)
and for admins in the web client.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.config import get_settings
from app.database import get_db
from app.models.book import Book, visible_books
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.reading_progress import ReadingProgress
from app.models.series import Series

router = APIRouter(tags=["stats"])


_bearer = HTTPBearer(auto_error=False)


class LatestAdded(BaseModel):
    title: str
    added_at: str


class ReadingStatus(BaseModel):
    unread: int
    in_progress: int
    finished: int


class StatsOut(BaseModel):
    total_books: int
    books_by_type: dict[str, int]
    series_by_type: dict[str, int]
    reading_status: ReadingStatus
    total_size_bytes: int
    latest_added: LatestAdded | None


def _require_stats_access(
    request: Request,
    x_kodex_api_key: str | None = Header(None),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> None:
    """The dashboard's fixed key, or an admin (the web client's statistics)."""
    settings = get_settings()
    if settings.stats_api_key and x_kodex_api_key == settings.stats_api_key:
        return
    if x_kodex_api_key is not None:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Kodex-Api-Key")
    require_admin(get_current_user(request, credentials=credentials, db=db))


@router.get("/stats", dependencies=[Depends(_require_stats_access)], response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)) -> dict:
    books_by_type = dict(
        db.query(Library.library_type, func.count(Book.id))
        .join(Book, Book.library_id == Library.id)
        .filter(visible_books())
        .group_by(Library.library_type)
        .all()
    )
    series_by_type = dict(
        db.query(Library.library_type, func.count(Series.id))
        .join(Series, Series.library_id == Library.id)
        .filter(Series.books.any(visible_books()))
        .group_by(Library.library_type)
        .all()
    )

    # Books hidden because their file is missing (Book.missing_since)
    # aren't part of the library as a reader sees it, so they don't count.
    total_books = db.query(func.count(Book.id)).filter(visible_books()).scalar() or 0
    total_size_bytes = int(db.query(func.coalesce(func.sum(Book.file_size), 0)).filter(visible_books()).scalar() or 0)
    visible_ids = db.query(Book.id).filter(visible_books())

    # ReadingProgress is per-user, but this app targets a single household
    # (see models/series.py's own note on is_following) — "finished by
    # anyone" / "in progress for anyone" is a reasonable global read for a
    # dashboard stat, not worth splitting per-user here.
    finished_ids_query = db.query(distinct(ReadingProgress.book_id)).filter(
        ReadingProgress.is_finished.is_(True), ReadingProgress.book_id.in_(visible_ids)
    )
    finished_count = finished_ids_query.count()
    in_progress_count = (
        db.query(distinct(ReadingProgress.book_id))
        .filter(ReadingProgress.is_finished.is_(False), ReadingProgress.book_id.in_(visible_ids))
        .filter(~ReadingProgress.book_id.in_(finished_ids_query))
        .count()
    )
    unread_count = max(total_books - finished_count - in_progress_count, 0)

    latest = (
        db.query(Book, BookMetadata)
        .outerjoin(BookMetadata, BookMetadata.book_id == Book.id)
        .filter(visible_books())
        .order_by(Book.added_at.desc())
        .first()
    )
    latest_added = None
    if latest:
        book, metadata = latest
        latest_added = {
            "title": metadata.title if metadata else book.file_path,
            "added_at": book.added_at.isoformat(),
        }

    return {
        "total_books": total_books,
        "books_by_type": {t.value: count for t, count in books_by_type.items()},
        "series_by_type": {t.value: count for t, count in series_by_type.items()},
        "reading_status": {
            "unread": unread_count,
            "in_progress": in_progress_count,
            "finished": finished_count,
        },
        "total_size_bytes": total_size_bytes,
        "latest_added": latest_added,
    }
