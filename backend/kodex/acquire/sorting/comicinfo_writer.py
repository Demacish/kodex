"""Writes/updates ComicInfo.xml inside CBZ archives for items the sorting
review queue has classified — see kodex/acquire/sorting/classifier.py for why this
matters: this collection's CBZ/CBR files mostly have no embedded
ComicInfo.xml at all, so a future rescan (or someone else's tool —
Kavita/Komga read the same standard) has nothing to go on. Writing it now,
while an item is still classified and sitting in the intake library,
means scan_library_task picks up Series/Manga/etc. automatically once the
file is moved — no separate metadata-backfill step needed.

CBR (RAR) is deliberately NOT supported here — RAR is a proprietary
archive format with no free/simple way to rewrite an entry the way a ZIP
allows; converting or otherwise handling CBR is a separate, bigger piece
of work than this.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from app.models.enums import BookEditionType
from app.scanning.parsers.number_utils import VULGAR_FRACTIONS, normalize_issue_number

_YEAR_RE = re.compile(r"\((\d{4})\)")
# "Absolute Corvid 001" / "Absolute Corvid 001 (2024) ..." — a 3-4 digit
# issue number preceded by the series name, optionally a half-issue suffix
# ("013.5", "013½") — the suffix is optional so a plain "001" still matches
# exactly as before.
_ISSUE_NUMBER_RE = re.compile(r"^(.*?)\s+(\d{3,4}(?:\.\d+)?[" + "".join(VULGAR_FRACTIONS) + r"]?)(?:\s|$)")
# "Absolute Corvid v01 - The Zoo (2025) ..." — a volume/trade number.
_VOLUME_RE = re.compile(r"^(.*?)\s+[vV](\d{1,3})\b")


def parse_series_and_number(folder_name: str) -> tuple[str, float | None, int | None]:
    """Best-effort split of a messy scene-release folder name into
    (series, number, year). Never raises — worst case, the whole name
    becomes the series with no number, which is still far more useful in
    ComicInfo.xml than nothing.
    """
    # Everything from the first " (" onward is release-group/format noise
    # ("(2024) (Webrip) (The Quiet Archivist-DCP)") in every sample seen —
    # strip it before trying to find a number.
    core = folder_name.split(" (")[0].strip()

    year_match = _YEAR_RE.search(folder_name)
    year = int(year_match.group(1)) if year_match else None

    if match := _ISSUE_NUMBER_RE.match(core):
        return match.group(1).strip(" -"), normalize_issue_number(match.group(2)), year

    if match := _VOLUME_RE.match(core):
        return match.group(1).strip(" -"), normalize_issue_number(match.group(2)), year

    return core, None, year


# "Hoshi no Uta volume 15" — manga releases spell "volume" out (vs. comics'
# terse "v01"/_VOLUME_RE above), so it needs its own pattern rather than
# reusing that one.
_MANGA_VOLUME_RE = re.compile(r"^(.*?)\s+volume\s+(\d{1,3})\b", re.IGNORECASE)


def parse_manga_volume_number(folder_name: str) -> float | None:
    """Best-effort volume number for a manga folder — the MANGA-library
    counterpart to parse_series_and_number()'s comics-oriented parsing
    (scanner.py only ever called that for LibraryType.COMICS; MANGA got
    no folder-name fallback at all, so any manga release without an
    embedded ComicInfo.xml <Number> — the common case for scanlation-
    group image dumps — kept Book.number permanently NULL, leaving the
    whole series unsorted and un-numbered in the UI). Returns None rather
    than guessing when the name doesn't contain "volume N".
    """
    core = folder_name.split(" (")[0].strip()
    if match := _MANGA_VOLUME_RE.match(core):
        return float(match.group(2))
    return None


_COLLECTED_KEYWORDS = ("tpb", "omnibus", "compendium", "deluxe edition", "vol.")


def detect_edition_type(folder_name: str) -> BookEditionType:
    """Single numbered issue vs. a collected edition (TPB/omnibus/deluxe/
    etc. collecting several issues under one file) — see
    BookEditionType's own docstring. A "v01"/"v02"-style volume number
    (_VOLUME_RE — the same pattern parse_series_and_number falls back to
    for a *number* above) is the strongest signal: this library's scene
    releases use "v0N" specifically for a collected volume, reserving a
    plain 3-4 digit number for a single issue (_ISSUE_NUMBER_RE) — this
    is exactly what motivated the feature (e.g. "Absolute Corvid v02 -
    Abomination" alongside individually-numbered "Absolute Corvid 002").
    A few literal keywords catch the rest ("... TPB 001 ...", "...
    Omnibus (2024) ...").
    """
    core = folder_name.split(" (")[0].strip()
    if _VOLUME_RE.match(core):
        return BookEditionType.COLLECTED
    lowered = core.lower()
    if any(keyword in lowered for keyword in _COLLECTED_KEYWORDS):
        return BookEditionType.COLLECTED
    return BookEditionType.ISSUE


def _build_comicinfo_xml(series: str, number: float | None, year: int | None, manga: str) -> bytes:
    root = ET.Element("ComicInfo")

    def add(tag: str, value: object) -> None:
        if value is None or value == "":
            return
        el = ET.SubElement(root, tag)
        el.text = str(value)

    add("Series", series)
    if number is not None:
        add("Number", int(number) if number == int(number) else number)
    add("Year", year)
    add("Manga", manga)

    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode").encode("utf-8")


def write_comicinfo_to_cbz(cbz_path: Path, series: str, number: float | None, year: int | None, manga: str) -> None:
    """Rewrites cbz_path with an added/replaced ComicInfo.xml, preserving
    every other entry byte-for-byte (including each one's original
    compression — images are already compressed, so this doesn't waste
    time re-deflating hundreds of JPEGs). Writes to a temp file in the
    same directory first and atomically renames over the original, so a
    crash mid-write can never leave a half-written archive in its place.

    Raises zipfile.BadZipFile if cbz_path isn't actually a valid zip
    (some scene "cbz" files are mislabeled) — the caller is expected to
    catch that per-file, same pattern as classifier.py's own
    ComicInfo-parsing try/except.
    """
    with zipfile.ZipFile(cbz_path, "r") as zf:
        infos = zf.infolist()
        comicinfo_name = next(
            (info.filename for info in infos if info.filename.lower().endswith("comicinfo.xml")), None
        )
        entries = [(info, zf.read(info.filename)) for info in infos if info.filename != comicinfo_name]

    xml_bytes = _build_comicinfo_xml(series, number, year, manga)

    fd, tmp_path_str = tempfile.mkstemp(suffix=".cbz.tmp", dir=cbz_path.parent)
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "wb") as tmp_f, zipfile.ZipFile(tmp_f, "w") as zf_out:
            zf_out.writestr(comicinfo_name or "ComicInfo.xml", xml_bytes, compress_type=zipfile.ZIP_DEFLATED)
            for info, data in entries:
                zf_out.writestr(info, data)
        tmp_path.replace(cbz_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
