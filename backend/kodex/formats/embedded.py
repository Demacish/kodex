"""Embedded metadata of one book, read once at scan time and stored in
``BookMetadata.raw`` so the matching engine never reopens the file:
ComicInfo.xml and MetronInfo.xml in CBZ/CBR archives and image folders,
the OPF package document of an EPUB, and a PDF's own title, authors and
printed ISBNs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from app.models.enums import BookFormat
from app.scanning import archive
from kodex.formats.comicinfo import parse_comicinfo_xml, parse_metroninfo_xml
from kodex.formats.opf import read_epub_opf
from kodex.formats.pdf import read_pdf

logger = logging.getLogger(__name__)

_SIDECARS = {
    "comicinfo.xml": ("comicinfo", parse_comicinfo_xml),
    "metroninfo.xml": ("metroninfo", parse_metroninfo_xml),
}


def _archive_members(path: Path, file_format: BookFormat) -> dict[str, bytes]:
    """The ComicInfo/MetronInfo entries of an archive or image folder, keyed
    by lowercase file name (only the shallowest one of each)."""
    found: dict[str, bytes] = {}
    with archive.open_book(path, file_format) as book:
        for name in _SIDECARS:
            if (data := book.sidecar(name)) is not None:
                found[name] = data
    return found


def read_embedded(path: Path, file_format: BookFormat) -> dict[str, Any]:
    """``{"comicinfo": {...}, "metroninfo": {...}, "opf": {...}, "pdf": {...}}``
    with only the parts the book has. Never raises: unreadable or malformed metadata
    is logged and left out."""
    result: dict[str, Any] = {}
    try:
        if file_format == BookFormat.EPUB:
            if opf := read_epub_opf(path):
                result["opf"] = opf
            return result
        if file_format == BookFormat.PDF:
            if pdf := read_pdf(path):
                result["pdf"] = pdf
            return result
        for name, data in _archive_members(path, file_format).items():
            key, parser = _SIDECARS[name]
            try:
                result[key] = parser(data)
            except ET.ParseError as exc:
                logger.warning("Malformed %s in %s: %s", name, path, exc)
    except Exception as exc:  # noqa: BLE001 - a bad file must never abort a scan
        logger.warning("Could not read embedded metadata from %s: %s", path, exc)
    return result
