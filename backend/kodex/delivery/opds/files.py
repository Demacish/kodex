"""What OPDS clients download: files, covers as JPEG and PSE pages as JPEG
(e-ink readers and older apps don't all show WebP), and the names and
positions their entries show."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.book import Book
from app.models.enums import PAGE_BASED_FORMATS
from app.models.reading_progress import ReadingProgress
from kodex.formats import archive
from kodex.library import covers
from kodex.library.paths import OutsideLibraries, within
from kodex.reading import pages, positions

_COVER_CACHE = "private, max-age=86400"


def title(book: Book) -> str:
    meta = book.book_metadata
    return meta.title if meta is not None and meta.title else PurePosixPath(book.file_path).stem


def filename(book: Book) -> str:
    return PurePosixPath(book.file_path).name


def last_page(book: Book, progress: ReadingProgress | None) -> int | None:
    """The 0-based page last read, for pse:lastRead."""
    if progress is None:
        return None
    return positions.page_index(book, progress.locator_kind, progress.position, progress.progress_percent)


def _book(db: Session, book_id: int) -> tuple[Book, Path]:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="No such book")
    try:
        path = within(get_settings().libraries_root, book.library.path, book.file_path)
    except OutsideLibraries as exc:
        raise HTTPException(status_code=404, detail="No such book") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="The file is missing; rescan the library")
    return book, path


def download(db: Session, book_id: int) -> FileResponse:
    book, path = _book(db, book_id)
    return FileResponse(path, filename=filename(book))


def cover(db: Session, book_id: int, size: str) -> Response:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="No such book")
    settings = get_settings()
    if not book.cover_key or not covers.cover_file(settings.covers_dir, book.id, size).is_file():
        covers.make(book, settings.libraries_root, settings.covers_dir, force=True)
        db.commit()
    found = covers.jpeg_file(settings.covers_dir, book.id, size)
    if found is None:
        raise HTTPException(status_code=404, detail="This book has no cover")
    return FileResponse(found, media_type="image/jpeg", headers={"Cache-Control": _COVER_CACHE})


def page(db: Session, book_id: int, index: int, max_width: int | None, cache_dir: Path) -> tuple[Book, Response]:
    book, path = _book(db, book_id)
    if book.file_format not in PAGE_BASED_FORMATS:
        raise HTTPException(status_code=400, detail="Only comics are streamed page by page")
    try:
        found = pages.page(book, path, index, cache_dir / "pages", max_width=max_width, encoding="jpeg")
    except IndexError as exc:
        raise HTTPException(status_code=404, detail="No such page") from exc
    except archive.ArchiveError as exc:
        raise HTTPException(status_code=422, detail=f"Unreadable page: {exc}") from exc
    return book, Response(found.data, media_type=found.media_type,
                          headers={"ETag": found.etag, "Cache-Control": _COVER_CACHE})  # fmt: skip
