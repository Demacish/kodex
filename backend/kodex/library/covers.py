"""Every book's cover in three sizes, made with pyvips (ADR 0015: a fraction
of Pillow's memory on large pages) and stored as WebP under
``covers_dir/generated``.

The source is the cover an enrichment downloaded, else the book's own: an
archive's front-cover page, an EPUB's cover image, a PDF's first page.
``Book.cover_key`` records which source the stored files were made from,
so a new download or a changed file makes them stale. A job makes the
missing ones after a scan; one asked for before that is made on the spot.
"""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.enums import PAGE_BASED_FORMATS, BookFormat

logger = logging.getLogger(__name__)

# Long edge in pixels: grid tiles, cards and lists, the book page.
SIZES = {"small": 200, "medium": 400, "large": 1000}
_PDF_RENDER_HEIGHT = 1600


def _pdf_first_page(path: Path) -> bytes | None:
    import pypdfium2 as pdfium  # imported lazily, like app/search/fulltext.py

    doc = pdfium.PdfDocument(str(path))
    try:
        if len(doc) == 0:
            return None
        page = doc[0]
        try:
            _, height = page.get_size()
            bitmap = page.render(scale=_PDF_RENDER_HEIGHT / max(height, 1))
            out = io.BytesIO()
            bitmap.to_pil().convert("RGB").save(out, "JPEG", quality=90)
            return out.getvalue()
        finally:
            page.close()
    finally:
        doc.close()


def source(book: Book, libraries_root: Path, covers_dir: Path) -> tuple[bytes, str] | None:
    """(image bytes, key) of the book's cover source, or None."""
    from kodex.formats.opf import read_epub_cover
    from kodex.library.paths import within
    from kodex.matching.covers import book_cover_page

    meta = book.book_metadata
    if meta is not None and meta.cover_path:
        downloaded = covers_dir / meta.cover_path
        if downloaded.is_file():
            return downloaded.read_bytes(), f"file:{meta.cover_path}:{downloaded.stat().st_mtime_ns}"
    path = within(libraries_root, book.library.path, book.file_path)
    identity = book.content_id or book.content_hash or f"{book.file_size}:{book.file_mtime}"
    try:
        if book.file_format in PAGE_BASED_FORMATS:
            data = book_cover_page(path, book.file_format, (meta.raw if meta else None) or {})
        elif book.file_format == BookFormat.EPUB:
            data = read_epub_cover(path)
        elif book.file_format == BookFormat.PDF:
            data = _pdf_first_page(path)
        else:
            data = None
    except Exception as exc:  # noqa: BLE001 - a book without a readable cover has none
        logger.info("No cover in %s: %s", path, exc)
        return None
    return (data, f"book:{identity}") if data else None


def cover_file(covers_dir: Path, book_id: int, size: str) -> Path:
    return covers_dir / "generated" / f"{book_id % 1000:03d}" / f"{book_id}-{size}.webp"


def jpeg_file(covers_dir: Path, book_id: int, size: str) -> Path | None:
    """The generated cover as JPEG, for clients that don't show WebP (OPDS
    readers on e-ink devices), made from the WebP one when it is newer."""
    import pyvips

    webp = cover_file(covers_dir, book_id, size)
    if not webp.is_file():
        return None
    target = webp.with_suffix(".jpg")
    if target.is_file() and target.stat().st_mtime_ns >= webp.stat().st_mtime_ns:
        return target
    image: Any = pyvips.Image.new_from_file(str(webp), access="sequential")
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(image.jpegsave_buffer(Q=85, strip=True))
    partial.replace(target)
    return target


def _key(descriptor: str) -> str:
    return hashlib.sha1(descriptor.encode(), usedforsecurity=False).hexdigest()


def make(book: Book, libraries_root: Path, covers_dir: Path, *, force: bool = False) -> bool:
    """Makes the book's three cover files if they are missing or stale;
    True when it wrote them. Sets ``book.cover_key`` (the caller commits)."""
    import pyvips

    found = source(book, libraries_root, covers_dir)
    if found is None:
        return False
    data, descriptor = found
    key = _key(descriptor)
    files = {size: cover_file(covers_dir, book.id, size) for size in SIZES}
    if not force and book.cover_key == key and all(f.is_file() for f in files.values()):
        return False
    for size, edge in SIZES.items():
        image: Any = pyvips.Image.thumbnail_buffer(data, edge, height=edge, size="down")
        if image.hasalpha():
            image = image.flatten(background=[255, 255, 255])
        target = files[size]
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        partial.write_bytes(image.webpsave_buffer(Q=82, strip=True))
        partial.replace(target)
    book.cover_key = key
    try:
        from kodex.matching.covers import hashes_from_bytes

        book.cover_phash = hashes_from_bytes(data)[0]
    except Exception:  # noqa: BLE001 - no hash just means no near-duplicate search
        book.cover_phash = None
    return True


def make_missing(db: Session, library_id: int, libraries_root: Path, covers_dir: Path, *, batch: int = 100) -> int:
    """Makes covers for the library's books that have none yet; the stale
    ones are remade when next asked for (see app/api/routes/books.py)."""
    made = 0
    ids = list(
        db.scalars(
            select(Book.id).where(Book.library_id == library_id, Book.missing_since.is_(None), Book.cover_key.is_(None))
        )
    )
    for start in range(0, len(ids), batch):
        for book in db.scalars(select(Book).where(Book.id.in_(ids[start : start + batch]))):
            try:
                made += make(book, libraries_root, covers_dir)
            except Exception:
                logger.exception("Could not make covers for book %s", book.id)
        db.commit()
    return made
