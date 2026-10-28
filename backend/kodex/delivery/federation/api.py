"""The read-only API other Kodex servers use to see what this one holds:
its libraries, and which of a list of books it has. With this server's
upload key (X-Kodex-Upload-Key) or an admin session."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require_admin_or_upload_key
from app.database import get_db
from app.models.book import Book, visible_books
from app.models.enums import BookEditionType
from app.models.library import Library
from app.models.series import Series
from app.workers.queue import get_scan_queue
from app.workers.tasks import scan_library_task

router = APIRouter(prefix="/federation", tags=["federation"], dependencies=[Depends(require_admin_or_upload_key)])


class BookRef(BaseModel):
    content_hash: str | None = None
    series_title: str | None = None
    number: float | None = None
    edition_type: BookEditionType = BookEditionType.ISSUE


class PresenceIn(BaseModel):
    books: list[BookRef] = Field(max_length=2000)


def _normalize(title: str) -> str:
    return " ".join(title.lower().split())


@router.get("/libraries")
def list_libraries(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [
        {"id": library.id, "name": library.name, "library_type": library.library_type}
        for library in db.query(Library).order_by(Library.name).all()
    ]


@router.post("/libraries/{library_id}/scan", status_code=202)
def scan_library(library_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Queues a scan: sent once by another server after copying a batch of
    books here (each upload skips its own scan)."""
    if db.get(Library, library_id) is None:
        raise HTTPException(status_code=404, detail="Library not found")
    job = get_scan_queue().enqueue(scan_library_task, library_id, job_timeout="2h")
    return {"job_id": job.id}


@router.post("/presence")
def presence(payload: PresenceIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """For each book, whether a visible book here is the same file
    (content_hash) or the same volume (series title, number and edition
    type: another release of it)."""
    hashes = {ref.content_hash for ref in payload.books if ref.content_hash}
    held_hashes: set[str] = set()
    if hashes:
        rows = db.query(Book.content_hash).filter(Book.content_hash.in_(hashes), visible_books()).all()
        held_hashes = {row[0] for row in rows if row[0]}

    titles = {_normalize(ref.series_title) for ref in payload.books if ref.series_title and ref.number is not None}
    held_volumes: set[tuple[str, float, BookEditionType]] = set()
    if titles:
        volumes = (
            db.query(Series.title, Book.number, Book.edition_type)
            .join(Book, Book.series_id == Series.id)
            .filter(func.lower(Series.title).in_(titles), Book.number.isnot(None), visible_books())
            .all()
        )
        held_volumes = {
            (_normalize(title), float(number), edition) for title, number, edition in volumes if number is not None
        }

    present = []
    for ref in payload.books:
        same_file = ref.content_hash in held_hashes if ref.content_hash else False
        same_volume = (
            ref.series_title is not None
            and ref.number is not None
            and (_normalize(ref.series_title), float(ref.number), ref.edition_type) in held_volumes
        )
        present.append(same_file or same_volume)
    return {"present": present}
