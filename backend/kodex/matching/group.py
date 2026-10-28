"""Local grouping: which series a book belongs to, decided without any
network call.

A series is identified by its key within a library: normalised title, run
(start year such as ``2016``, a volume such as ``v2``, or for e-books the
author) and format family (``issue``, ``collected``, ``manga``, ``book``).
How the key is read depends on the library's grouping strategy:

``folder`` (Komga style)
    The first folder below the library root is the series, whatever the
    files say. Predictable for libraries that are already sorted.
``metadata`` (Kavita style, the default)
    ComicInfo/MetronInfo ``Series`` + ``Volume`` (or the OPF series for
    e-books) group books; the parsed file name, helped by the series
    folder's name, is the fallback. One folder per issue therefore still
    gives one series. TPBs and omnibuses form their own series
    (``collected``) next to the issues; manga volumes and chapters share one.
``comicvine`` (Mylar3/Kapowarr layout)
    A ``Series (Year)`` folder is one run, like ``folder``; its ``cvinfo``
    or ``[cv-ID]`` then binds it to the run without a search.

A series' id never changes. When a book's key stops matching its series
(a renamed folder, a retagged file, a strategy switch), the change is
proposed in the review queue instead of moving the book; see
``kodex.matching.series_ops``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import PurePath
from typing import Any, Literal

from kodex.matching.normalize import norm
from kodex.matching.parse import Kind, ParsedName, parse_filename, parse_folder

Strategy = Literal["folder", "metadata", "comicvine"]
FormatFamily = Literal["issue", "collected", "manga", "book"]
STRATEGIES: tuple[Strategy, ...] = ("folder", "metadata", "comicvine")

# Subfolders that hold extras of the series around them.
_EXTRA_FOLDERS = {"specials", "special", "extras", "annuals", "one-shots", "oneshots", "covers"}
_COLLECTED_FORMATS = {
    "tpb", "trade paperback", "omnibus", "hardcover", "hc", "graphic novel", "gn", "compendium", "absolute",
    "deluxe", "library", "collection", "collected",
}  # fmt: skip
_MANGA_VALUES = {"yes", "yesandrighttoleft", "yes and right to left"}


@dataclass(frozen=True)
class SeriesKey:
    title: str
    norm_title: str
    run: str
    format_family: str
    start_year: int | None
    # The first folder below the library root (v1's Series.path), if any.
    folder: str | None

    @property
    def key(self) -> str:
        return f"{self.norm_title}|{self.run}|{self.format_family}"


def book_kind(library_type: str, file_format: str, embedded: dict[str, Any]) -> Kind:
    """How to read a book's name: from the library type, or for a mixed
    library from the file itself."""
    library_type = library_type.lower()
    if library_type == "comics":
        return "comic"
    if library_type == "manga":
        return "manga"
    if library_type == "ebooks":
        return "book"
    if file_format.lower() in ("epub", "pdf"):
        return "book"
    manga = str((embedded.get("comicinfo") or {}).get("manga", "")).strip().lower()
    return "manga" if manga in _MANGA_VALUES else "comic"


def series_folder(relative_path: PurePath) -> str | None:
    """The folder that stands for the series: the first level below the
    library root, skipping nothing; None for a book in the root."""
    return relative_path.parts[0] if len(relative_path.parts) > 1 else None


def _hint_folder(relative_path: PurePath) -> str | None:
    """The folder whose name describes the series for this book: its own
    folder, or the one above an extras folder like ``Specials/``."""
    parents = list(relative_path.parts[:-1])
    while parents and parents[-1].strip().lower() in _EXTRA_FOLDERS:
        parents.pop()
    return parents[-1] if parents else None


def _format_family(kind: Kind, parsed: ParsedName, comicinfo: dict[str, Any]) -> FormatFamily:
    if kind == "manga":
        return "manga"
    if kind == "book":
        return "book"
    ci_format = str(comicinfo.get("format", "")).strip().lower()
    if ci_format in _COLLECTED_FORMATS or parsed.format == "collected":
        return "collected"
    return "issue"


def _run_from_volume(volume: str) -> tuple[str, int | None]:
    """ComicInfo ``Volume``: a value from 1900 up is the start year (the
    Mylar/Komga convention), anything else a volume number."""
    if volume.isdigit() and int(volume) >= 1900:
        return volume, int(volume)
    return f"v{volume}", None


# ComicTagger's rule: a comic with no number and more than this many pages
# is a collected edition (a TPB or hardcover), not a single issue.
COLLECTED_MIN_PAGES = 100


def collected_by_size(parsed: ParsedName, kind: Kind, page_count: int | None, embedded: dict[str, Any]) -> ParsedName:
    """``Harbour Lights (2016).cbz`` with 130 pages is the collected edition,
    and so is ``Quiet Coast Book 02`` with 300 (its number is the volume's)."""
    if kind != "comic":
        return parsed
    book = bool(parsed.issue and not parsed.volume and "numbered as a book" in parsed.notes)
    if book and parsed.format == "collected":  # "... Deluxe Edition Book 01"
        return replace(parsed, volume=parsed.issue, issue=None)
    if parsed.format != "issue" or not page_count or page_count <= COLLECTED_MIN_PAGES:
        return parsed
    if book:
        return replace(parsed, format="collected", volume=parsed.issue, issue=None)
    if parsed.issue or parsed.volume or (embedded.get("comicinfo") or {}).get("number"):
        return parsed
    return replace(parsed, format="collected")


def parse_book_name(relative_path: PurePath, kind: Kind) -> ParsedName:
    """The book's file (or image folder) name, read with its folder's name
    as the series hint."""
    hint = _hint_folder(relative_path)
    return parse_filename(
        relative_path.name, kind=kind, series_hint=parse_folder(hint, kind=kind).series if hint else None
    )


def series_key(
    *,
    strategy: Strategy,
    kind: Kind,
    relative_path: PurePath,
    parsed: ParsedName,
    embedded: dict[str, Any],
) -> SeriesKey | None:
    """The series key for one book; None for a book that belongs to no
    series (a file in the root of a ``folder`` library, as in v1)."""
    folder = series_folder(relative_path)
    comicinfo = embedded.get("comicinfo") or {}
    family = _format_family(kind, parsed, comicinfo)

    if strategy in ("folder", "comicvine"):
        if folder is None:
            return None
        whole_folder = parse_folder(folder, kind=kind)
        folder_title = whole_folder.series or folder
        year = whole_folder.series_year
        # One series per folder: the family is fixed so TPBs stay with it.
        return SeriesKey(folder, norm(folder_title) or folder.casefold(), f"folder:{folder}", "issue" if kind == "comic" else family,
                         year, folder)  # fmt: skip

    if kind == "book":
        return _book_key(relative_path, parsed, embedded, folder)

    metroninfo = embedded.get("metroninfo") or {}
    metron_series = metroninfo.get("series") or {}
    title: str | None = comicinfo.get("series") or metron_series.get("name")
    run, start_year = "", None
    if title:
        if volume := str(comicinfo.get("volume") or "").strip():
            run, start_year = _run_from_volume(volume)
        elif metron_series.get("start_year"):
            start_year = int(metron_series["start_year"])
            run = str(start_year)
    else:
        title = parsed.series
        hint = _hint_folder(relative_path)
        folder_parsed = parse_folder(hint, kind=kind) if hint else None
        if not title and folder_parsed is not None:
            title = folder_parsed.series
        title = title or relative_path.stem
        start_year = parsed.series_year
        if start_year is None and folder_parsed is not None and norm(folder_parsed.series) == norm(title):
            start_year = folder_parsed.series_year
        if start_year is not None:
            run = str(start_year)
        elif kind == "comic" and parsed.volume and parsed.issue:
            run = f"v{parsed.volume}"
    if kind == "manga":
        run = ""  # a manga volume is a book of the series, not another run
    return SeriesKey(title, norm(title) or title.casefold(), run, family, start_year, folder)


def _book_key(relative_path: PurePath, parsed: ParsedName, embedded: dict[str, Any], folder: str | None) -> SeriesKey:
    """E-books: the OPF series, else the book itself, keyed with its first
    author so two books with the same title stay apart."""
    opf = embedded.get("opf") or {}
    authors = opf.get("authors") or []
    author = norm(authors[0]) if authors else ""
    title = opf.get("series") or parsed.series or opf.get("title") or parsed.title or relative_path.stem
    return SeriesKey(title, norm(title) or title.casefold(), author, "book", None, folder)


_COMICINFO_BOOK_FORMATS = {
    "annual": "annual", "special": "special", "fcbd": "special", "one-shot": "one_shot", "one shot": "one_shot",
    "oneshot": "one_shot", "tpb": "collected", "trade paperback": "collected", "omnibus": "collected",
    "hardcover": "collected", "hc": "collected", "graphic novel": "collected", "gn": "collected",
    "compendium": "collected", "absolute": "collected", "deluxe": "collected", "library": "collected",
}  # fmt: skip


def book_format(kind: Kind, parsed: ParsedName, embedded: dict[str, Any]) -> str:
    """The book's format: ComicInfo ``Format`` when it names one, else what
    the file name says."""
    if kind == "book":
        return "book"
    ci_format = str((embedded.get("comicinfo") or {}).get("format", "")).strip().lower()
    if ci_format in _COMICINFO_BOOK_FORMATS:
        return _COMICINFO_BOOK_FORMATS[ci_format]
    return parsed.format
