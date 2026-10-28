"""Parse EPUB metadata (the OPF package document) without pulling in a large
dependency — an EPUB is just a zip file with a well-defined structure.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

_ISBN_RE = re.compile(r"(?:isbn[:\s]*)?((?:97[89][ -]?)?\d[\d -]{8,15}[\dXx])", re.IGNORECASE)

_NS = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def _find_opf_path(zf: zipfile.ZipFile) -> str:
    container_xml = zf.read("META-INF/container.xml")
    root = ET.fromstring(container_xml)
    rootfile = root.find(".//container:rootfile", _NS)
    if rootfile is None or "full-path" not in rootfile.attrib:
        raise ValueError("EPUB container.xml has no rootfile entry")
    return rootfile.attrib["full-path"]


def parse_epub_metadata(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        opf_path = _find_opf_path(zf)
        opf_root = ET.fromstring(zf.read(opf_path))

        # Spine item count is a rough proxy for "length" — not shown to
        # users as a page count, just used to sanity-check that the file
        # parsed correctly.
        spine = opf_root.find("opf:spine", _NS)
        spine_items = len(spine.findall("opf:itemref", _NS)) if spine is not None else 0

    metadata_el = opf_root.find("opf:metadata", _NS)
    result: dict = {"spine_item_count": spine_items}
    if metadata_el is None:
        return result

    if (title_el := metadata_el.find("dc:title", _NS)) is not None and title_el.text:
        result["title"] = title_el.text.strip()

    authors = [
        creator.text.strip()
        for creator in metadata_el.findall("dc:creator", _NS)
        if creator.text and creator.text.strip()
    ]
    if authors:
        result["authors"] = authors

    if (lang_el := metadata_el.find("dc:language", _NS)) is not None and lang_el.text:
        result["language"] = lang_el.text.strip()

    if (desc_el := metadata_el.find("dc:description", _NS)) is not None and desc_el.text:
        result["summary"] = desc_el.text.strip()

    if (pub_el := metadata_el.find("dc:publisher", _NS)) is not None and pub_el.text:
        result["publisher"] = pub_el.text.strip()

    if (date_el := metadata_el.find("dc:date", _NS)) is not None and date_el.text:
        year_str = date_el.text.strip()[:4]
        if year_str.isdigit():
            result["published_year"] = int(year_str)

    for identifier_el in metadata_el.findall("dc:identifier", _NS):
        if not identifier_el.text:
            continue
        scheme = (identifier_el.attrib.get("{http://www.idpf.org/2007/opf}scheme") or "").lower()
        text = identifier_el.text.strip()

        if scheme == "isbn":
            digits = re.sub(r"[- ]", "", text)
        elif match := _ISBN_RE.search(text):
            digits = re.sub(r"[- ]", "", match.group(1))
        else:
            continue

        if len(digits) in (10, 13):
            result["isbn"] = digits
            break

    return result
