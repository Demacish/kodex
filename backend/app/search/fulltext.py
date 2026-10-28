"""Fulltext extraction and indexing for EPUB and PDF — CBZ/CBR are images
without a text layer, so they're skipped (see the architecture plan's
"Sök och indexering" section on why OCR isn't in scope here).

This is a manually-triggered, per-library job (POST /libraries/{id}/
fulltext-index), never run automatically on scan — extracting full book
text is far more expensive than reading metadata. The text goes to
content_index_entries, which kodex.discovery.search searches.
"""

from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.book import Book
from app.models.content_index import ContentIndexEntry
from app.models.enums import BookFormat
from app.models.library import Library

logger = logging.getLogger(__name__)

_CONTAINER_NS = {"container": "urn:oasis:names:tc:opendocument:xmlns:container"}
_OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_xhtml_tags(xhtml_bytes: bytes) -> str:
    text = xhtml_bytes.decode("utf-8", errors="replace")
    text = _TAG_RE.sub(" ", text)
    return " ".join(text.split())


def extract_epub_chapters(path: Path) -> list[tuple[str, str]]:
    """Returns (position, text) per spine item, in reading order. `position`
    is the chapter's href within the EPUB — the reader frontend can jump
    straight to that file, which is more directly useful than a synthetic
    CFI would be for a search-result "jump to this hit" link.
    """
    from xml.etree import ElementTree as ET

    chapters: list[tuple[str, str]] = []
    with zipfile.ZipFile(path) as zf:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile_el = container.find(".//container:rootfile", _CONTAINER_NS)
        if rootfile_el is None:
            return chapters
        rootfile = rootfile_el.attrib["full-path"]

        opf_root = ET.fromstring(zf.read(rootfile))
        opf_dir = Path(rootfile).parent

        manifest = {
            item.attrib["id"]: item.attrib["href"]
            for item in opf_root.findall("opf:manifest/opf:item", _OPF_NS)
            if item.attrib.get("media-type") == "application/xhtml+xml"
        }

        for itemref in opf_root.findall("opf:spine/opf:itemref", _OPF_NS):
            href = manifest.get(itemref.attrib.get("idref", ""))
            if not href:
                continue
            zip_path = f"{opf_dir}/{href}" if str(opf_dir) != "." else href
            zip_path = zip_path.replace("\\", "/")
            try:
                text = _strip_xhtml_tags(zf.read(zip_path))
            except KeyError:
                logger.warning("EPUB manifest references missing file %s in %s", zip_path, path)
                continue
            if text:
                chapters.append((href, text))

    return chapters


def extract_pdf_pages(path: Path) -> list[tuple[str, str]]:
    import pypdfium2 as pdfium  # imported lazily, like scanning/parsers/pdf_meta.py

    pages: list[tuple[str, str]] = []
    doc = pdfium.PdfDocument(str(path))
    try:
        for page_number in range(1, len(doc) + 1):
            page = doc[page_number - 1]
            textpage = page.get_textpage()
            try:
                text = textpage.get_text_bounded().strip()
            finally:
                textpage.close()
                page.close()
            if text:
                pages.append((str(page_number), text))
    finally:
        doc.close()
    return pages


def index_book_fulltext(db: Session, book: Book) -> int:
    """Extracts and indexes fulltext for one book, replacing any previous
    ContentIndexEntry rows for it. Returns the number of entries indexed
    (0 for an unsupported format, an empty book, or an extraction
    failure — the caller can't easily tell those apart from the count
    alone, but all three just mean "nothing to search" either way).
    """
    settings = get_settings()
    path = settings.libraries_root / book.library.path / book.file_path

    if book.file_format == BookFormat.EPUB:
        extractor = extract_epub_chapters
    elif book.file_format == BookFormat.PDF:
        extractor = extract_pdf_pages
    else:
        return 0

    try:
        entries = extractor(path)
    except Exception:
        logger.exception("Fulltext extraction failed for book %s (%s)", book.id, path)
        return 0

    db.query(ContentIndexEntry).filter(ContentIndexEntry.book_id == book.id).delete()
    for position, text in entries:
        db.add(ContentIndexEntry(book_id=book.id, position=position, text=text))
    db.flush()

    return len(entries)


def index_library_fulltext(db: Session, library: Library) -> dict:
    books = (
        db.query(Book)
        .filter(Book.library_id == library.id, Book.file_format.in_([BookFormat.EPUB, BookFormat.PDF]))
        .all()
    )

    books_indexed = 0
    total_entries = 0
    for book in books:
        count = index_book_fulltext(db, book)
        db.commit()
        if count:
            books_indexed += 1
            total_entries += count

    return {"books_considered": len(books), "books_indexed": books_indexed, "entries_indexed": total_entries}
