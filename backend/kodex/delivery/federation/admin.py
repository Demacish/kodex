"""The admins' side: which of a series' books each other server has, and
copying the rest there."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models.book import Book, visible_books
from app.models.series import Series
from app.models.user import User
from app.schemas.common import JobQueuedOut
from app.workers.queue import get_download_queue
from app.workers.tasks import copy_books_to_peer_task
from kodex.delivery.federation.peers import PeerError, configured_peers, get_peer

router = APIRouter(prefix="/peers", tags=["peers"])


class CopyIn(BaseModel):
    peer: str
    library_id: int
    book_ids: list[int] = Field(min_length=1, max_length=500)


class PeerOut(BaseModel):
    name: str


class PeerLibraryOut(BaseModel):
    id: int
    name: str
    library_type: str | None = None


class PeerBookOut(BaseModel):
    book_id: int
    number: float | None
    edition_type: str
    title: str
    present: bool


class PeerSeriesOut(BaseModel):
    """One server: its libraries, and which of the series' books it has."""

    name: str
    error: str | None
    libraries: list[PeerLibraryOut]
    books: list[PeerBookOut]


def _series_books(db: Session, series_id: int) -> list[Book]:
    return (
        db.query(Book)
        .filter(Book.series_id == series_id, visible_books())
        # "issue" sorts after "collected": descending puts single issues first.
        .order_by(Book.edition_type.desc(), Book.number.asc().nulls_last(), Book.file_path)
        .all()
    )


@router.get("", response_model=list[PeerOut])
def list_peers(_admin: User = Depends(require_admin)) -> list[dict[str, Any]]:
    return [{"name": peer.name} for peer in configured_peers()]


@router.get("/series/{series_id}", response_model=list[PeerSeriesOut])
def series_on_peers(series_id: int, db: Session = Depends(get_db),
                    _admin: User = Depends(require_admin)) -> list[dict[str, Any]]:  # fmt: skip
    """Per server: its libraries (to copy into) and whether it has each of
    this series' books. A server that can't be reached comes back with
    ``error``; the others still answer."""
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")
    books = _series_books(db, series_id)
    refs = [
        {"content_hash": book.content_hash, "series_title": series.title, "number": book.number,
         "edition_type": book.edition_type.value}
        for book in books
    ]  # fmt: skip
    results: list[dict[str, Any]] = []
    for peer in configured_peers():
        try:
            libraries = peer.libraries()
            present = peer.presence(refs) if refs else []
        except PeerError as exc:
            results.append({"name": peer.name, "error": str(exc), "libraries": [], "books": []})
            continue
        results.append({
            "name": peer.name,
            "error": None,
            "libraries": libraries,
            "books": [
                {"book_id": book.id, "number": book.number, "edition_type": book.edition_type,
                 "title": book.book_metadata.title if book.book_metadata else book.file_path, "present": bool(is_present)}
                for book, is_present in zip(books, present, strict=False)
            ],
        })  # fmt: skip
    return results


@router.post("/copy", status_code=202, response_model=JobQueuedOut)
def copy_to_peer(
    payload: CopyIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict[str, Any]:
    """Queues copying these books to another server's library, each into the
    series folder it has here. The outcome per book shows under Admin › Jobb."""
    if get_peer(payload.peer) is None:
        raise HTTPException(status_code=404, detail=f"Unknown server: {payload.peer}")
    found = {row[0] for row in db.query(Book.id).filter(Book.id.in_(payload.book_ids)).all()}
    missing = set(payload.book_ids) - found
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown book id(s): {sorted(missing)}")
    job = get_download_queue().enqueue(copy_books_to_peer_task, payload.peer, payload.library_id, payload.book_ids,
                                       job_timeout="6h")  # fmt: skip
    return {"job_id": job.id}
