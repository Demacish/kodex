"""The library module's API (admin only): duplicate books, writing
metadata back into a library's files and converting a CBR or CB7 to CBZ."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models.book import Book
from app.models.enums import BookFormat
from app.models.library import Library
from app.models.user import User
from app.schemas.common import JobQueuedOut
from kodex.library import duplicates

router = APIRouter(prefix="/library", tags=["library"])


def _summary(book: Book) -> dict[str, Any]:
    return {
        "id": book.id, "library_id": book.library_id, "series_id": book.series_id, "file_path": book.file_path,
        "file_format": book.file_format.value, "file_size": book.file_size, "number_label": book.number_label,
        "title": book.book_metadata.title if book.book_metadata else None,
    }  # fmt: skip


class DuplicateBookOut(BaseModel):
    id: int
    library_id: int
    series_id: int | None
    file_path: str
    file_format: str
    file_size: int
    number_label: str | None
    title: str | None


class DuplicatesOut(BaseModel):
    exact: list[list[DuplicateBookOut]]
    similar: list[list[DuplicateBookOut]]


@router.get("/duplicates", response_model=DuplicatesOut)
def list_duplicates(db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> dict[str, Any]:
    """Exact duplicates (the same pages; the first book in each group is the
    one the others point at) and similar books (same number in the same
    series, nearly the same cover, different pages)."""
    exact, similar = duplicates.exact_groups(db), duplicates.similar_groups(db)
    ids = {i for group in [*exact, *similar] for i in group}
    books = {b.id: b for b in db.scalars(select(Book).where(Book.id.in_(ids)))} if ids else {}
    return {
        "exact": [[_summary(books[i]) for i in group if i in books] for group in exact],
        "similar": [[_summary(books[i]) for i in group if i in books] for group in similar],
    }


@router.post("/libraries/{library_id}/write-back", status_code=202, response_model=JobQueuedOut)
def write_back(library_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> dict[str, Any]:
    from app.workers.queue import get_scan_queue
    from app.workers.tasks import write_back_library_task

    library = db.get(Library, library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")
    if library.read_only or not library.write_back:
        raise HTTPException(status_code=409, detail="Write-back is off or the library is read-only")
    job = get_scan_queue().enqueue(write_back_library_task, library_id, job_id=f"write-back-{library_id}")
    return {"job_id": job.id}


@router.post("/books/{book_id}/convert", status_code=202, response_model=JobQueuedOut)
def convert(book_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> dict[str, Any]:
    from app.workers.queue import get_scan_queue
    from app.workers.tasks import convert_book_task

    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if book.file_format not in (BookFormat.CBR, BookFormat.CB7):
        raise HTTPException(status_code=409, detail="Only CBR and CB7 books are converted")
    if book.library.read_only:
        raise HTTPException(status_code=409, detail="The library is read-only")
    job = get_scan_queue().enqueue(convert_book_task, book_id, job_id=f"convert-{book_id}")
    return {"job_id": job.id}
