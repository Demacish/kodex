"""Bookmarks: places in a book a user wants to find again, on any device.

A client names its bookmarks itself (a UUID), so saving one is a PUT that
can be sent again without making two, and one made offline goes up when
the device is back. Removing one is a DELETE that is fine twice. Each user
sees only their own."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.book import Book
from app.models.user import User
from kodex.reading.models import Bookmark
from kodex.reading.positions import MAX_LENGTH, LocatorKind

router = APIRouter(tags=["bookmarks"])

_UUID = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


class BookmarkIn(BaseModel):
    book_id: int
    # The reader's own locator and its kind (kodex.reading.positions).
    position: str = Field(min_length=1, max_length=MAX_LENGTH)
    locator_kind: LocatorKind
    progress_percent: float = Field(ge=0, le=100)
    chapter: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=500)
    # When the device made it; the server's clock when left out.
    created_at: dt.datetime | None = None


class BookmarkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    book_id: int
    position: str
    locator_kind: LocatorKind
    progress_percent: float
    chapter: str | None
    note: str | None
    created_at: dt.datetime


@router.get("/bookmarks", response_model=list[BookmarkOut])
def list_bookmarks(
    book_id: int | None = Query(None, description="Only this book's"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[BookmarkOut]:
    """The user's bookmarks, in reading order within each book."""
    query = select(Bookmark).where(Bookmark.user_id == user.id)
    if book_id is not None:
        query = query.where(Bookmark.book_id == book_id)
    rows = db.scalars(query.order_by(Bookmark.book_id, Bookmark.progress_percent, Bookmark.created_at))
    return [BookmarkOut.model_validate(row) for row in rows]


@router.put("/bookmarks/{bookmark_id}", response_model=BookmarkOut)
def save_bookmark(
    body: BookmarkIn,
    bookmark_id: str = Path(pattern=_UUID),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BookmarkOut:
    """Makes the bookmark, or changes it (its note) when it is there."""
    if db.get(Book, body.book_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    bookmark_id = bookmark_id.lower()
    bookmark = db.get(Bookmark, bookmark_id)
    if bookmark is not None and bookmark.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Another user has a bookmark with this id")
    if bookmark is None:
        bookmark = Bookmark(id=bookmark_id, user_id=user.id)
        if body.created_at is not None:
            bookmark.created_at = body.created_at
        db.add(bookmark)
    bookmark.book_id = body.book_id
    bookmark.position = body.position
    bookmark.locator_kind = body.locator_kind
    bookmark.progress_percent = body.progress_percent
    bookmark.chapter = body.chapter
    bookmark.note = body.note
    db.commit()
    db.refresh(bookmark)
    return BookmarkOut.model_validate(bookmark)


@router.delete("/bookmarks/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bookmark(
    bookmark_id: str = Path(pattern=_UUID), db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> None:
    """Removes the bookmark; one that isn't there (any more) is fine."""
    db.execute(delete(Bookmark).where(Bookmark.id == bookmark_id.lower(), Bookmark.user_id == user.id))
    db.commit()
