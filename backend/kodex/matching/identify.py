"""Id resolution: external ids found in a book, its folder or its name, so
a match can be looked up directly ("identify by ID") instead of searched.

Sources, strongest first:

1. Inside the file: ComicInfo ``Web`` and ``Notes`` (Comic Vine URLs where
   ``4050-`` is a series and ``4000-`` an issue, ComicTagger's
   ``[Issue ID 123]`` and ``[CVDB123]``, MetronTagger's ``[issue_id:123]``,
   ``urn:comicvine:…``, GCD, MangaDex, AniList, MAL and MangaUpdates URLs),
   ``GTIN``, MetronInfo ``<IDS>``, and the identifiers of an EPUB's OPF.
2. Next to it: a Calibre ``metadata.opf`` in the book's folder, and in the
   series folder Mylar's ``cvinfo`` and ``series.json``.
3. In the folder or file name: ``[cv-123]``, ``cv:123``, ``4050-123``.

A Comic Vine issue id gives both the run and the issue once looked up; a
Metron id gives its ``cv_id`` and ``gcd_id`` for free.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from kodex.formats.opf import isbn13, parse_opf

logger = logging.getLogger(__name__)

RefKind = Literal["series", "issue", "book"]


@dataclass(frozen=True)
class ExternalRef:
    provider: str
    kind: RefKind
    id: str
    source: str


_TEXT_PATTERNS: list[tuple[re.Pattern[str], str, RefKind]] = [
    (re.compile(r"comicvine\.gamespot\.com/[^\s/]*/?4050-(\d+)", re.I), "comicvine", "series"),
    (re.compile(r"comicvine\.gamespot\.com/[^\s/]*/?4000-(\d+)", re.I), "comicvine", "issue"),
    (re.compile(r"(?<![\w-])4050-(\d+)\b"), "comicvine", "series"),
    (re.compile(r"(?<![\w-])4000-(\d+)\b"), "comicvine", "issue"),
    (re.compile(r"\[Issue ID (\d+)\]", re.I), "comicvine", "issue"),
    (re.compile(r"\[CVDB(\d+)\]", re.I), "comicvine", "issue"),
    (re.compile(r"urn:comicvine:(?:series|volume):(\d+)", re.I), "comicvine", "series"),
    (re.compile(r"urn:comicvine:issue:(\d+)", re.I), "comicvine", "issue"),
    (re.compile(r"\[issue_id:(\d+)\]", re.I), "metron", "issue"),
    (re.compile(r"\[series_id:(\d+)\]", re.I), "metron", "series"),
    (re.compile(r"comics\.org/issue/(\d+)", re.I), "gcd", "issue"),
    (re.compile(r"comics\.org/series/(\d+)", re.I), "gcd", "series"),
    (re.compile(r"mangadex\.org/title/([0-9a-f-]{36})", re.I), "mangadex", "series"),
    (re.compile(r"anilist\.co/manga/(\d+)", re.I), "anilist", "series"),
    (re.compile(r"myanimelist\.net/manga/(\d+)", re.I), "mal", "series"),
    (re.compile(r"mangaupdates\.com/series/([0-9a-z]+)", re.I), "mangaupdates", "series"),
    (re.compile(r"metron\.cloud/series/(\d+)", re.I), "metron", "series"),
    (re.compile(r"metron\.cloud/issue/(\d+)", re.I), "metron", "issue"),
]
# In folder and file names; "[cv-123]" is Kapowarr's and Komf's convention.
_NAME_PATTERNS: list[tuple[re.Pattern[str], str, RefKind]] = [
    (re.compile(r"[\[(]cv[-_:]?(\d+)[\])]", re.I), "comicvine", "series"),
    (re.compile(r"(?<![a-z])cv:(\d+)\b", re.I), "comicvine", "series"),
    (re.compile(r"(?<![\w-])4050-(\d+)\b"), "comicvine", "series"),
    (re.compile(r"(?<![\w-])4000-(\d+)\b"), "comicvine", "issue"),
    (re.compile(r"[\[(]mdx?[-:]([0-9a-f-]{36})[\])]", re.I), "mangadex", "series"),
]
_METRON_SOURCES = {
    "metron": "metron", "comic vine": "comicvine", "comicvine": "comicvine", "grand comics database": "gcd",
    "gcd": "gcd", "mangadex": "mangadex", "anilist": "anilist", "myanimelist": "mal", "mangaupdates": "mangaupdates",
    "league of comic geeks": "locg", "kitsu": "kitsu",
}  # fmt: skip


def ids_from_text(
    text: str, source: str, *, patterns: list[tuple[re.Pattern[str], str, RefKind]] | None = None
) -> list[ExternalRef]:
    refs: list[ExternalRef] = []
    for pattern, provider, kind in patterns or _TEXT_PATTERNS:
        for match in pattern.finditer(text):
            ref = ExternalRef(
                provider, kind, match.group(1).lower() if provider == "mangadex" else match.group(1), source
            )
            if ref not in refs:
                refs.append(ref)
    return refs


def ids_from_embedded(embedded: dict[str, Any]) -> list[ExternalRef]:
    refs: list[ExternalRef] = []
    comicinfo = embedded.get("comicinfo") or {}
    for field in ("web", "notes"):
        if value := comicinfo.get(field):
            refs += ids_from_text(str(value), f"comicinfo.{field}")
    if gtin := comicinfo.get("gtin"):
        refs += _gtin_refs(str(gtin), "comicinfo.gtin")

    metroninfo = embedded.get("metroninfo") or {}
    for entry in metroninfo.get("ids", []):
        provider = _METRON_SOURCES.get(str(entry.get("source", "")).strip().lower())
        if provider and entry.get("id"):
            refs.append(ExternalRef(provider, "issue", str(entry["id"]), "metroninfo"))
    if series_id := (metroninfo.get("series") or {}).get("id"):
        refs.append(ExternalRef("metron", "series", str(series_id), "metroninfo"))
    for code in (metroninfo.get("gtin") or {}).values():
        refs += _gtin_refs(str(code), "metroninfo.gtin")

    opf = embedded.get("opf") or {}
    refs += _opf_refs(opf, "opf")
    return _dedupe(refs)


def _gtin_refs(code: str, source: str) -> list[ExternalRef]:
    digits = re.sub(r"\D", "", code)
    if (digits.startswith(("978", "979")) and len(digits) == 13) or len(digits) == 10:
        if isbn := isbn13(digits):
            return [ExternalRef("isbn", "book", isbn, source)]
    if len(digits) in (12, 13, 17):
        return [ExternalRef("upc", "issue", digits, source)]
    return []


def _opf_refs(opf: dict[str, Any], source: str) -> list[ExternalRef]:
    refs = []
    for scheme, value in (opf.get("identifiers") or {}).items():
        provider = {"isbn": "isbn", "google": "google_books", "goodreads": "goodreads", "openlibrary": "open_library",
                    "hardcover": "hardcover", "amazon": "amazon", "mobi-asin": "amazon"}.get(scheme)  # fmt: skip
        if provider:
            refs.append(ExternalRef(provider, "book", str(value), source))
    return refs


def ids_from_folder(folder: Path) -> list[ExternalRef]:
    """Mylar's ``cvinfo`` and ``series.json`` and Calibre's
    ``metadata.opf`` in a folder."""
    refs: list[ExternalRef] = []
    cvinfo = folder / "cvinfo"
    if cvinfo.is_file():
        refs += ids_from_text(cvinfo.read_text(errors="replace"), "cvinfo")
    series_json = folder / "series.json"
    if series_json.is_file():
        try:
            metadata = json.loads(series_json.read_text()).get("metadata", {})
            if comicid := metadata.get("comicid"):
                refs.append(ExternalRef("comicvine", "series", str(comicid), "series.json"))
        except (ValueError, AttributeError) as exc:
            logger.warning("Unreadable %s: %s", series_json, exc)
    calibre = folder / "metadata.opf"
    if calibre.is_file():
        try:
            refs += _opf_refs(parse_opf(calibre.read_bytes()), "metadata.opf")
        except Exception as exc:  # noqa: BLE001 - a broken sidecar is just ignored
            logger.warning("Unreadable %s: %s", calibre, exc)
    return refs


def ids_from_name(name: str, source: str) -> list[ExternalRef]:
    return ids_from_text(name, source, patterns=_NAME_PATTERNS)


def identify(relative_path: Path, library_root: Path, embedded: dict[str, Any]) -> list[ExternalRef]:
    """Every id for the book at ``library_root / relative_path``, strongest
    source first."""
    refs = ids_from_embedded(embedded)
    book_dir = (library_root / relative_path).parent
    folders = [book_dir]
    # The series folder (first level) carries cvinfo/series.json even when
    # issues sit in their own subfolders.
    if len(relative_path.parts) > 1:
        series_dir = library_root / relative_path.parts[0]
        if series_dir != book_dir:
            folders.append(series_dir)
    for folder in folders:
        refs += ids_from_folder(folder)
    refs += ids_from_name(relative_path.name, "filename")
    for part in reversed(relative_path.parts[:-1]):
        refs += ids_from_name(part, "folder")
    return _dedupe(refs)


def _dedupe(refs: list[ExternalRef]) -> list[ExternalRef]:
    seen: set[tuple[str, str, str]] = set()
    out = []
    for ref in refs:
        key = (ref.provider, ref.kind, ref.id)
        if key not in seen:
            seen.add(key)
            out.append(ref)
    return out


def strongest(refs: list[ExternalRef], provider: str, kind: RefKind) -> str | None:
    return next((ref.id for ref in refs if ref.provider == provider and ref.kind == kind), None)
