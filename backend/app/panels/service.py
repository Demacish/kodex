"""Ties panel detection to the database and the archive page-cache — the
counterpart to app/enrichment/engine.py for Guided View. Called from
app/workers/tasks.py's per-book/per-library job bodies, never directly from
an API route (those only enqueue).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.book import Book
from app.models.enums import PAGE_BASED_FORMATS, BookFormat, PanelStatus
from app.models.panel import BookPagePanel, BookPanelStatus
from app.panels.detector import detect_panels
from app.scanning import archive

logger = logging.getLogger(__name__)

_PAGE_BASED_FORMATS = PAGE_BASED_FORMATS


def _absolute_path(book: Book):
    settings = get_settings()
    return settings.libraries_root / book.library.path / book.file_path


def _get_or_create_status(db: Session, book_id: int) -> BookPanelStatus:
    status = db.get(BookPanelStatus, book_id)
    if status is None:
        status = BookPanelStatus(book_id=book_id, status=PanelStatus.PENDING)
        db.add(status)
    return status


def detect_panels_for_book(db: Session, book: Book, *, force: bool = False) -> bool:
    """Runs panel detection for every page of one book and stores the
    result, replacing whatever was stored before. Returns True if anything
    was (re-)processed, False if skipped (already done and not forced,
    unsupported format, or the feature is globally disabled).

    Mirrors app/enrichment/engine.py's auto_enrich_book shape: safe to call
    repeatedly (a re-run of a DONE book without force is a no-op), and the
    caller (app/workers/tasks.py) is responsible for committing/rolling
    back and for not letting one bad book stop a library-wide run.
    """
    settings = get_settings()
    if not settings.guided_view_enabled:
        status = _get_or_create_status(db, book.id)
        status.status = PanelStatus.UNSUPPORTED
        status.error = "Guided View är globalt inaktiverat (guided_view_enabled=false)"
        return False

    if book.file_format not in _PAGE_BASED_FORMATS:
        status = _get_or_create_status(db, book.id)
        status.status = PanelStatus.UNSUPPORTED
        status.error = f"Filformat {book.file_format.value} stöds inte av Guided View"
        return False

    existing = db.get(BookPanelStatus, book.id)
    if existing is not None and existing.status == PanelStatus.DONE and not force:
        return False

    status = _get_or_create_status(db, book.id)

    if not book.page_count:
        status.status = PanelStatus.FAILED
        status.error = "Boken saknar page_count — skanna om biblioteket först"
        return False

    path = _absolute_path(book)
    cache_dir = settings.covers_dir / "pages" / str(book.id)

    # Replace, not merge — a re-run (force=True, or a book that previously
    # FAILED partway through) should never leave stale panels from an
    # earlier attempt mixed in with new ones.
    db.query(BookPagePanel).filter(BookPagePanel.book_id == book.id).delete()

    pages_with_panels = 0
    pages_processed = 0
    try:
        for page_index in range(book.page_count):
            if book.file_format == BookFormat.IMAGE_FOLDER:
                images = archive.list_image_folder_pages(path)
                if page_index >= len(images):
                    continue
                page_path = images[page_index]
            else:
                page_path = archive.extract_page(path, book.file_format, page_index, cache_dir)

            panels = detect_panels(page_path)
            pages_processed += 1
            if not panels:
                continue

            pages_with_panels += 1
            for order_index, panel in enumerate(panels):
                db.add(
                    BookPagePanel(
                        book_id=book.id,
                        page_index=page_index,
                        order_index=order_index,
                        x=panel.x,
                        y=panel.y,
                        w=panel.w,
                        h=panel.h,
                    )
                )
    except (archive.ArchiveError, ValueError, OSError) as exc:
        logger.exception("Panel detection failed for book %s at page %s", book.id, page_index)
        status.status = PanelStatus.FAILED
        status.error = str(exc)
        status.pages_processed = pages_processed
        status.pages_with_panels = pages_with_panels
        return True

    status.status = PanelStatus.DONE
    status.pages_processed = pages_processed
    status.pages_with_panels = pages_with_panels
    status.error = None
    logger.info(
        "Panel detection done for book %s: %d/%d pages got panels",
        book.id,
        pages_with_panels,
        pages_processed,
    )
    return True
