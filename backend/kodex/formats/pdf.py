"""What a PDF says about itself: the title and authors in its document
info dictionary or XMP packet, and the ISBNs printed on its first pages
(a publisher's e-book carries them on the copyright page).

Producers fill the info dictionary with whatever the authoring tool had:
``chapter01_fm.indd`` as the title, ``Sys`` or ``Administrator`` as the author.
Values like these are left out rather than passed on as evidence.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from kodex.formats.opf import isbn13

logger = logging.getLogger(__name__)

# The copyright page comes within the first few pages; ISBNs further in
# are usually other books' (advertisements at the back).
FRONT_PAGES = 8
_MAX_ISBNS = 4

_ISBN = re.compile(r"ISBN(?:[-\s]?1[03])?[^0-9\n]{0,20}([0-9][0-9\s-]{8,16}[0-9Xx])", re.IGNORECASE)
_TOOL_PREFIX = re.compile(r"^(?:microsoft (?:word|powerpoint) - |untitled - )", re.IGNORECASE)
_FILE_NAME = re.compile(r"\.(?:indd|indb|qxd|qxp|docx?|pdf|tex|dvi|ps|rtf|fm|book|p65|pm\d?)$", re.IGNORECASE)
_PLACEHOLDER_TITLES = {"untitled", "unknown", "title", "document", "book", "cover", "pdf", "none", "null"}
_PLACEHOLDER_AUTHORS = {
    "admin", "administrator", "author", "default", "owner", "pc", "sys", "system", "unknown", "user", "none", "null",
}  # fmt: skip
_TOOL_AUTHORS = re.compile(
    r"\b(?:adobe|acrobat|indesign|quarkxpress|microsoft|latex|tex|calibre|abbyy)\b", re.IGNORECASE
)


def usable_title(title: str | None) -> str | None:
    """The title, or None when it is an authoring tool's leftover: a file
    name, a placeholder or no letters at all."""
    text = _TOOL_PREFIX.sub("", (title or "").strip()).strip()
    if not text or _FILE_NAME.search(text) or text.lower() in _PLACEHOLDER_TITLES:
        return None
    if not any(c.isalpha() for c in text):
        return None
    return text


def split_authors(text: str) -> list[str]:
    """``Ada Alder II and Bo Brook`` → two authors. A comma
    separates authors only when each side is a whole name, so ``Corey,
    James S. A.`` stays one."""
    parts = [p.strip() for p in re.split(r"\s*(?:;|/|&|\band\b|\bund\b|\boch\b)\s*", text) if p.strip()]
    authors: list[str] = []
    for part in parts:
        pieces = [p.strip() for p in part.split(",") if p.strip()]
        if len(pieces) > 1 and all(len(p.split()) >= 2 for p in pieces):
            authors.extend(pieces)
        else:
            authors.append(part)
    return [a for a in authors if _usable_author(a)]


def _usable_author(name: str) -> bool:
    letters = sum(c.isalpha() for c in name)
    if letters <= 3 or "@" in name or name.lower() in _PLACEHOLDER_AUTHORS:
        return False
    return not _TOOL_AUTHORS.search(name)


def isbns_in_text(text: str) -> list[str]:
    """Every valid ISBN after an "ISBN" label, as ISBN-13, in order."""
    found: list[str] = []
    for match in _ISBN.finditer(text):
        digits = re.sub(r"[^0-9Xx]", "", match.group(1))
        # An ISBN-13 starts with its prefix; anything else is an ISBN-10.
        normalised = isbn13(digits[:13] if digits[:3] in ("978", "979") else digits[:10])
        if normalised and normalised not in found:
            found.append(normalised)
    return found


def _info(pdf: Any) -> tuple[str, str]:
    def text(key: str) -> str:
        value = pdf.docinfo.get(key)
        return str(value).strip() if value is not None else ""

    title, author = text("/Title"), text("/Author")
    if not title or not author:
        try:
            xmp = pdf.open_metadata()
            title = title or str(xmp.get("dc:title") or "").strip()
            creators = xmp.get("dc:creator") or []
            author = author or (" and ".join(creators) if isinstance(creators, list) else str(creators))
        except Exception:  # noqa: BLE001 - a malformed XMP packet leaves the info dictionary
            pass
    return title, author


def _front_text(path: Path) -> str:
    import pypdfium2 as pdfium  # imported lazily, like app/search/fulltext.py

    texts = []
    doc = pdfium.PdfDocument(str(path))
    try:
        for index in range(min(FRONT_PAGES, len(doc))):
            page = doc[index]
            textpage = page.get_textpage()
            try:
                texts.append(textpage.get_text_bounded())
            finally:
                textpage.close()
                page.close()
    finally:
        doc.close()
    return "\n".join(texts)


def read_pdf(path: Path) -> dict[str, Any]:
    """``{"title": ..., "authors": [...], "isbn": [...]}`` with only what
    the PDF has; raises on an unreadable file."""
    import pikepdf  # imported lazily, like app/scanning/parsers/pdf_meta.py

    with pikepdf.open(path) as pdf:
        title, author = _info(pdf)
    result: dict[str, Any] = {}
    if usable := usable_title(title):
        result["title"] = usable
    if authors := split_authors(author):
        result["authors"] = authors
    try:
        isbns = isbns_in_text(_front_text(path))[:_MAX_ISBNS]
    except Exception as exc:  # noqa: BLE001 - the text layer is optional
        logger.info("Could not read the text of %s: %s", path, exc)
        isbns = []
    if isbns:
        result["isbn"] = isbns
    return result
