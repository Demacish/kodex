"""Admin inbox for flagged pages (B6, Page Manager) — see books.py's
flag_page/unflag_page/resolve_page_flag for the reader-facing side. A
separate top-level router (not nested under /books/{id}, unlike those)
since this lists/acts across every book at once.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models.book import Book
from app.models.page_flag import BookPageFlag
from app.models.user import User
from app.schemas.page_flag import PageFlagAdminOut

router = APIRouter(prefix="/page-flags", tags=["page-flags"])


@router.get("", response_model=list[PageFlagAdminOut])
def list_page_flags(
    resolved: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[dict]:
    """`resolved=false` (the admin inbox's default view) shows the review
    queue; omit the filter to see everything, including past verdicts.
    """
    query = db.query(BookPageFlag, Book).join(Book, Book.id == BookPageFlag.book_id)
    if resolved is not None:
        query = query.filter(BookPageFlag.resolved.is_(resolved))
    query = query.order_by(BookPageFlag.flagged_at.desc())

    rows = []
    for flag, book in query.all():
        book_title = book.book_metadata.title if book.book_metadata else book.file_path
        rows.append(
            {
                "id": flag.id,
                "book_id": flag.book_id,
                "page_index": flag.page_index,
                "reason": flag.reason,
                "note": flag.note,
                "flagged_by_user_id": flag.flagged_by_user_id,
                "flagged_at": flag.flagged_at,
                "resolved": flag.resolved,
                "resolved_action": flag.resolved_action,
                "resolved_at": flag.resolved_at,
                "book_title": book_title,
                "flagged_by_username": flag.flagged_by.username if flag.flagged_by else None,
            }
        )
    return rows
