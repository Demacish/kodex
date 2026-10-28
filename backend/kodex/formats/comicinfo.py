"""Readers for the embedded metadata files of comic archives: ComicInfo.xml
(Anansi Project v2.1, the format Kavita, Komga and ComicTagger write) and
MetronInfo.xml (MetronTagger's richer format with provider ids).

Both return plain dicts with snake_case keys and only the fields present,
so they can be stored as-is in ``BookMetadata.raw`` and read by the
matching engine without opening the file again.
"""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

# ComicInfo v2.1 elements read as text, with their dict keys.
_COMICINFO_TEXT = {
    "Title": "title", "Series": "series", "Number": "number", "Volume": "volume", "AlternateSeries": "alternate_series",
    "AlternateNumber": "alternate_number", "Summary": "summary", "Notes": "notes", "Writer": "writer",
    "Penciller": "penciller", "Inker": "inker", "Colorist": "colorist", "Letterer": "letterer",
    "CoverArtist": "cover_artist", "Editor": "editor", "Translator": "translator", "Publisher": "publisher",
    "Imprint": "imprint", "Genre": "genre", "Tags": "tags", "Web": "web", "LanguageISO": "language", "Format": "format",
    "BlackAndWhite": "black_and_white", "Manga": "manga", "Characters": "characters", "Teams": "teams",
    "Locations": "locations", "ScanInformation": "scan_information", "StoryArc": "story_arc",
    "StoryArcNumber": "story_arc_number", "SeriesGroup": "series_group", "AgeRating": "age_rating",
    "MainCharacterOrTeam": "main_character_or_team", "Review": "review", "GTIN": "gtin",
    "LocalizedSeries": "localized_series", "SeriesSort": "series_sort",
}  # fmt: skip
_COMICINFO_INT = {"Count": "count", "AlternateCount": "alternate_count", "Year": "year", "Month": "month", "Day": "day",
                  "PageCount": "page_count"}  # fmt: skip


def _local(tag: str) -> str:
    """Element name without its XML namespace."""
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element) -> dict[str, ET.Element]:
    return {_local(child.tag): child for child in element}


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def parse_comicinfo_xml(data: bytes) -> dict[str, Any]:
    """Every ComicInfo v2.1 field present in ``data``. Raises
    ``ET.ParseError`` on malformed XML."""
    root = ET.fromstring(data)
    children = _children(root)
    result: dict[str, Any] = {}
    for tag, key in _COMICINFO_TEXT.items():
        if (value := _text(children.get(tag))) is not None:
            result[key] = value
    for tag, key in _COMICINFO_INT.items():
        if (value := _text(children.get(tag))) is not None:
            try:
                result[key] = int(value)
            except ValueError:
                continue
    if (rating := _text(children.get("CommunityRating"))) is not None:
        try:
            result["community_rating"] = float(rating)
        except ValueError:
            pass
    pages = children.get("Pages")
    if pages is not None:
        result["pages"] = [
            {_snake(name): value for name, value in page.attrib.items()} for page in pages if _local(page.tag) == "Page"
        ]
    return result


def _snake(name: str) -> str:
    out = []
    for i, char in enumerate(name):
        if char.isupper() and i:
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def front_cover_index(comicinfo: dict[str, Any]) -> int | None:
    """The page marked ``Type="FrontCover"``, if any."""
    for page in comicinfo.get("pages", []):
        if page.get("type", "").lower() == "frontcover":
            try:
                return int(page["image"])
            except KeyError, ValueError:
                return None
    return None


def parse_metroninfo_xml(data: bytes) -> dict[str, Any]:
    """The MetronInfo.xml fields the matching engine uses: ids per source,
    series (name, volume, format, start year), number, publisher, cover
    date, title and GTIN."""
    root = ET.fromstring(data)
    children = _children(root)
    result: dict[str, Any] = {}

    ids: list[dict[str, Any]] = []
    for container in ("IDS", "ID"):
        node = children.get(container)
        if node is None:
            continue
        entries = [node] if container == "ID" else [c for c in node if _local(c.tag) == "ID"]
        for entry in entries:
            if (value := _text(entry)) is not None:
                ids.append(
                    {
                        "source": entry.attrib.get("source", ""),
                        "id": value,
                        "primary": entry.attrib.get("primary") == "true",
                    }
                )
    if ids:
        result["ids"] = ids

    series = children.get("Series")
    if series is not None:
        series_children = _children(series)
        info: dict[str, Any] = {}
        for tag, key in (("Name", "name"), ("SortName", "sort_name"), ("Format", "format"), ("Volume", "volume")):
            if (value := _text(series_children.get(tag))) is not None:
                info[key] = value
        if (start := _text(series_children.get("StartYear"))) is not None and start.isdigit():
            info["start_year"] = int(start)
        if (lang := series.attrib.get("lang")) is not None:
            info["language"] = lang
        if (series_id := series.attrib.get("id")) is not None:
            info["id"] = series_id
        result["series"] = info

    publisher = children.get("Publisher")
    if publisher is not None:
        name = _text(_children(publisher).get("Name")) or _text(publisher)
        if name:
            result["publisher"] = name
    for tag, key in (
        ("Number", "number"),
        ("Title", "title"),
        ("CoverDate", "cover_date"),
        ("StoreDate", "store_date"),
    ):
        if (value := _text(children.get(tag))) is not None:
            result[key] = value
    gtin = children.get("GTIN")
    if gtin is not None:
        codes = {_local(c.tag).lower(): _text(c) for c in gtin if _text(c)}
        if codes:
            result["gtin"] = codes
    return result


# ComicInfo v2.1's element order (its XSD is a sequence).
_ORDER = [
    "Title", "Series", "Number", "Count", "Volume", "AlternateSeries", "AlternateNumber", "AlternateCount", "Summary",
    "Notes", "Year", "Month", "Day", "Writer", "Penciller", "Inker", "Colorist", "Letterer", "CoverArtist", "Editor",
    "Translator", "Publisher", "Imprint", "Genre", "Tags", "Web", "PageCount", "LanguageISO", "Format",
    "BlackAndWhite", "Manga", "Characters", "Teams", "Locations", "ScanInformation", "StoryArc", "StoryArcNumber",
    "SeriesGroup", "AgeRating", "Pages", "CommunityRating", "MainCharacterOrTeam", "Review", "GTIN",
    "LocalizedSeries", "SeriesSort",
]  # fmt: skip
_XSI = "http://www.w3.org/2001/XMLSchema-instance"


def build_comicinfo_xml(values: dict[str, str | int | None], existing: bytes | None = None) -> bytes:
    """A ComicInfo.xml with ``values`` (element name → value; None removes
    the element) merged into ``existing``: every element Kodex doesn't set,
    such as the page list with its FrontCover, is kept as it was."""
    root: ET.Element | None = None
    if existing:
        try:
            root = ET.fromstring(existing)
        except ET.ParseError:
            root = None
    if root is None or _local(root.tag) != "ComicInfo":
        root = ET.Element("ComicInfo")
        root.set(f"{{{_XSI}}}noNamespaceSchemaLocation", "ComicInfo.xsd")
    namespace = root.tag[: -len("ComicInfo")]
    elements = {_local(child.tag): child for child in root}
    for name, value in values.items():
        if value is None or value == "":
            if name in elements:
                root.remove(elements.pop(name))
            continue
        element = elements.get(name)
        if element is None:
            element = ET.SubElement(root, f"{namespace}{name}")
            elements[name] = element
        element.text = str(value)
    rank = {name: i for i, name in enumerate(_ORDER)}
    children = sorted(root, key=lambda child: rank.get(_local(child.tag), len(_ORDER)))
    for child in list(root):
        root.remove(child)
    root.extend(children)
    ET.register_namespace("xsi", _XSI)
    ET.indent(root, space="  ")
    body: bytes = ET.tostring(root, encoding="utf-8")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + body + b"\n"
