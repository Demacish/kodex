"""Parse ComicInfo.xml — the de facto metadata standard for CBZ/CBR files,
also used by Kavita and Komga, so existing files carry straight over.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from app.scanning.parsers.number_utils import normalize_issue_number


def parse_comicinfo(xml_bytes: bytes) -> dict:
    """Return a dict of the fields we care about. Missing fields are omitted
    rather than set to None, so callers can merge this over defaults safely.
    """
    root = ET.fromstring(xml_bytes)

    def text(tag: str) -> str | None:
        el = root.find(tag)
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
        return None

    result: dict = {}

    if title := text("Title"):
        result["title"] = title
    if series := text("Series"):
        # Used by the scanner as a fallback series title when the folder
        # name is ambiguous.
        result["series"] = series
    if summary := text("Summary"):
        result["summary"] = summary
    if publisher := text("Publisher"):
        result["publisher"] = publisher
    if genre := text("Genre"):
        result["genres"] = [g.strip() for g in genre.split(",") if g.strip()]
    if story_arc := text("StoryArc"):
        arcs = [a.strip() for a in story_arc.split(",") if a.strip()]
        result["story_arcs"] = arcs
        # StoryArcNumber is a second comma-separated list, positionally
        # matched to StoryArc (e.g. StoryArc="Silent Tides, Civil War",
        # StoryArcNumber="3, 1" means issue #3 of Silent Tides and #1 of
        # Civil War). Zipped rather than trusted to always line up 1:1 —
        # real-world ComicInfo.xml files aren't always internally
        # consistent, and a mismatched extra number is more useful dropped
        # than misattributed to the wrong arc.
        if story_arc_number := text("StoryArcNumber"):
            numbers: dict[str, float] = {}
            for arc, number in zip(arcs, (n.strip() for n in story_arc_number.split(",")), strict=False):
                try:
                    numbers[arc] = float(number)
                except ValueError:
                    continue
            if numbers:
                result["story_arc_numbers"] = numbers
    if language := text("LanguageISO"):
        result["language"] = language
    if manga := text("Manga"):
        # ComicInfo's own comic-vs-manga signal ("Unknown"/"No"/"Yes"/
        # "YesAndRightToLeft") — used by kodex/acquire/sorting/classifier.py, not
        # currently mapped onto BookMetadata (no column for it there yet).
        result["manga"] = manga
    if number := text("Number"):
        if (parsed_number := normalize_issue_number(number)) is not None:
            result["number"] = parsed_number
    if year := text("Year"):
        try:
            result["published_year"] = int(year)
        except ValueError:
            pass

    authors: list[str] = []
    for tag in ("Writer", "Penciller", "Inker", "Colorist", "CoverArtist"):
        if value := text(tag):
            authors.extend(a.strip() for a in value.split(",") if a.strip())
    if authors:
        # Preserve order, drop duplicates.
        result["authors"] = list(dict.fromkeys(authors))

    return result
