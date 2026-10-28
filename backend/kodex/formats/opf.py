"""OPF package metadata, from an EPUB's package document or a Calibre
``metadata.opf`` next to a book: title, creators, language, publisher,
date, identifiers (ISBN normalised to ISBN-13) and series (Calibre's
``calibre:series`` meta or EPUB 3 ``belongs-to-collection``)."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

_NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
}
_OPF_SCHEME = "{http://www.idpf.org/2007/opf}scheme"


def isbn13(raw: str) -> str | None:
    """``0-306-40615-2`` → ``9780306406157``; None unless ``raw`` is a
    valid ISBN-10 or ISBN-13."""
    digits = re.sub(r"[^0-9Xx]", "", raw).upper()
    if len(digits) == 10 and digits[:9].isdigit() and (digits[9].isdigit() or digits[9] == "X"):
        if sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(digits)) % 11:
            return None
        body = "978" + digits[:9]
    elif len(digits) == 13 and digits.isdigit():
        body = digits[:12]
    else:
        return None
    check = (10 - sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body)) % 10) % 10
    if len(digits) == 13 and int(digits[12]) != check:
        return None
    return body + str(check)


def parse_opf(data: bytes) -> dict[str, Any]:
    root = ET.fromstring(data)
    metadata = root.find("opf:metadata", _NS)
    if metadata is None:
        metadata = root.find("metadata")
    if metadata is None:
        return {}

    def texts(tag: str) -> list[str]:
        return [el.text.strip() for el in metadata.findall(f"dc:{tag}", _NS) if el.text and el.text.strip()]

    result: dict[str, Any] = {}
    if titles := texts("title"):
        result["title"] = titles[0]
    if creators := texts("creator"):
        result["authors"] = creators
    for tag in ("language", "publisher", "date", "description", "source"):
        if values := texts(tag):
            result[tag] = values[0]

    identifiers: dict[str, str] = {}
    for el in metadata.findall("dc:identifier", _NS):
        if not el.text or not el.text.strip():
            continue
        value = el.text.strip()
        scheme = (el.attrib.get(_OPF_SCHEME) or "").lower()
        lowered = value.lower()
        if scheme == "isbn" or lowered.startswith("urn:isbn:") or lowered.startswith("isbn"):
            if normalised := isbn13(value.split(":", 1)[-1] if lowered.startswith("isbn:") else value):
                identifiers.setdefault("isbn", normalised)
        elif scheme in ("calibre", "uuid", "mobi-asin", "amazon", "goodreads", "google", "openlibrary", "hardcover"):
            identifiers[scheme] = value
        elif ":" in value and lowered.split(":", 1)[0] in ("goodreads", "google", "amazon", "openlibrary", "hardcover"):
            prefix, _, rest = value.partition(":")
            identifiers[prefix.lower()] = rest
    if identifiers:
        result["identifiers"] = identifiers

    # Calibre series, then EPUB 3 collections.
    series = index = None
    for meta in metadata.findall("opf:meta", _NS) + metadata.findall("meta"):
        name = meta.attrib.get("name")
        if name == "calibre:series":
            series = meta.attrib.get("content")
        elif name == "calibre:series_index":
            index = meta.attrib.get("content")
    if series is None:
        collections = {
            m.attrib.get("id"): (m.text or "").strip()
            for m in metadata.findall("opf:meta", _NS)
            if m.attrib.get("property") == "belongs-to-collection"
        }
        for meta in metadata.findall("opf:meta", _NS):
            refines = (meta.attrib.get("refines") or "").lstrip("#")
            if meta.attrib.get("property") == "group-position" and refines in collections:
                series, index = collections[refines], (meta.text or "").strip()
        if series is None and collections:
            series = next(iter(collections.values()))
    if series:
        result["series"] = series
        if index:
            result["series_index"] = index
    return result


def read_epub_opf(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile = container.find(".//container:rootfile", _NS)
        if rootfile is None or not rootfile.attrib.get("full-path"):
            return {}
        return parse_opf(zf.read(rootfile.attrib["full-path"]))


def _cover_href(root: ET.Element) -> str | None:
    """The cover image's manifest href: EPUB 3's ``cover-image`` property,
    else EPUB 2's ``<meta name="cover" content="item-id">``."""
    manifest = root.find("opf:manifest", _NS)
    if manifest is None:
        return None
    items = manifest.findall("opf:item", _NS)
    for item in items:
        if "cover-image" in (item.attrib.get("properties") or "").split():
            return item.attrib.get("href")
    for meta in root.iter(f"{{{_NS['opf']}}}meta"):
        if meta.attrib.get("name") != "cover":
            continue
        wanted = meta.attrib.get("content")
        for item in items:
            if item.attrib.get("id") == wanted and (item.attrib.get("media-type") or "").startswith("image/"):
                return item.attrib.get("href")
    return None


def read_epub_cover(path: Path) -> bytes | None:
    """The EPUB's cover image, or None when it names none."""
    from posixpath import dirname, join, normpath
    from urllib.parse import unquote

    with zipfile.ZipFile(path) as zf:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile = container.find(".//container:rootfile", _NS)
        if rootfile is None or not rootfile.attrib.get("full-path"):
            return None
        opf_path = rootfile.attrib["full-path"]
        href = _cover_href(ET.fromstring(zf.read(opf_path)))
        if not href:
            return None
        entry = normpath(join(dirname(opf_path), unquote(href)))
        info = zf.getinfo(entry) if entry in zf.namelist() else None
        if info is None or info.file_size > 64 * 1024 * 1024:
            return None
        return zf.read(info)
