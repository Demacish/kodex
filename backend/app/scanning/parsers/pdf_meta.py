"""Parse PDF metadata and page count using pikepdf.

The document info dictionary is read first; the XMP packet only fills in
what it lacks (some producers write only XMP).
"""

from __future__ import annotations

from pathlib import Path


def _docinfo_text(pdf, key: str) -> str:
    value = pdf.docinfo.get(key)
    return str(value).strip() if value is not None else ""


def parse_pdf_metadata(path: Path) -> dict:
    import pikepdf  # imported lazily, like the other optional native parsers

    result: dict = {}
    with pikepdf.open(path) as pdf:
        result["page_count"] = len(pdf.pages)
        title = _docinfo_text(pdf, "/Title")
        author = _docinfo_text(pdf, "/Author")
        if not title or not author:
            try:
                xmp = pdf.open_metadata()
                title = title or str(xmp.get("dc:title") or "").strip()
                author = author or ", ".join(xmp.get("dc:creator") or [])
            except Exception:  # noqa: BLE001 - a malformed XMP packet must not hide the page count
                pass
        if title:
            result["title"] = title
        if author:
            result["authors"] = [a.strip() for a in author.split(",") if a.strip()]
    return result
