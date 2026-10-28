"""Best-effort type classification for one top-level intake item (a folder
of files, or occasionally a loose file) — comics vs. manga vs. ebooks.

Deliberately conservative: this collection's files mostly lack useful
embedded signal (spot-checked several release-group CBRs and a manga
folder during development — none had ComicInfo.xml at all), so most
cbz/cbr and loose-image items end up needing a human's call rather than a
guess. Returning (None, reason) routes an item to the manual review queue
(see kodex/acquire/sorting/api.py) instead of risking a wrong auto-sort — a
file move is much harder to silently notice and fix than a queued review
item.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from app.models.enums import BookFormat, LibraryType
from app.scanning import archive
from app.scanning.scanner import _extract_comicinfo

BOOK_EXTENSIONS = {".pdf", ".epub"}
COMIC_EXTENSIONS = {".cbz", ".cbr", ".cb7"}

# Release-naming conventions, used only when ComicInfo.xml is missing or
# says nothing about Manga (the common case here — see the module
# docstring). Each pattern on its own is a strong convention, not a
# guess: scanlation/manga releases number chapters ("c012", "Ch. 12",
# "Chapter 12"); western digital comic
# releases carry a 3-4 digit issue number plus a "(2019)" year, or a
# "(Digital)"/"(Webrip)" tag. A spelled-out "Volume 3" is deliberately
# NOT a manga signal — western trades use it too ("Saga Volume 1"). A
# name matching BOTH families is treated as no signal at all and stays in
# the review queue.
_MANGA_NAME_PATTERNS = (
    re.compile(r"(?:^|[\s_\-\[(])(?:ch|chap|chapter)\.?\s*\d{1,4}\b", re.IGNORECASE),
    re.compile(r"(?:^|[\s_\-\[(])c\d{2,4}\b", re.IGNORECASE),
)
_COMIC_NAME_PATTERNS = (
    re.compile(r"(?:^|\s)#?\d{3,4}(?:\.\d+)?\s.*\(\d{4}\)"),
    re.compile(r"\((?:digital|webrip|digital-empire|zone-empire)\b", re.IGNORECASE),
    re.compile(r"(?:^|\s)(?:tpb|omnibus|annual)\b", re.IGNORECASE),
)


def _classify_by_name(names: list[str]) -> tuple[LibraryType | None, str]:
    """Release-name signal for comics vs. manga — see the patterns above."""
    manga_hit = next((n for n in names if any(p.search(n) for p in _MANGA_NAME_PATTERNS)), None)
    comic_hit = next((n for n in names if any(p.search(n) for p in _COMIC_NAME_PATTERNS)), None)
    if manga_hit and not comic_hit:
        return LibraryType.MANGA, f"Filnamn ser ut som manga (kapitel/volym): {manga_hit}"
    if comic_hit and not manga_hit:
        return LibraryType.COMICS, f"Filnamn ser ut som serietidning (nummer/år/digital): {comic_hit}"
    return None, ""


def _candidate_names(path: Path) -> list[str]:
    """The item's own name plus its comic archives' and image subfolders'
    names (stems), at most a handful — enough for the naming conventions
    above without walking a huge folder end to end."""
    names = [path.stem if path.is_file() else path.name]
    if path.is_dir():
        for _dirpath, dirnames, filenames in os.walk(path):
            names.extend(Path(f).stem for f in filenames if Path(f).suffix.lower() in COMIC_EXTENSIONS)
            names.extend(dirnames)
            if len(names) > 20:
                break
    return names[:20]


def _collect_extensions(root: Path) -> set[str]:
    extensions: set[str] = set()
    for _dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            extensions.add(Path(name).suffix.lower())
    return extensions


def _first_comic_archive(root: Path) -> tuple[Path, BookFormat] | None:
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            suffix = Path(name).suffix.lower()
            if suffix == ".cbz":
                return Path(dirpath) / name, BookFormat.CBZ
            if suffix == ".cbr":
                return Path(dirpath) / name, BookFormat.CBR
            if suffix == ".cb7":
                return Path(dirpath) / name, BookFormat.CB7
    return None


def classify(path: Path) -> tuple[LibraryType | None, str]:
    """Returns (detected_type, human-readable reason). detected_type is
    None when nothing here is confident enough to act on automatically.
    """
    if path.is_file():
        suffix = path.suffix.lower()
        if suffix in BOOK_EXTENSIONS:
            return LibraryType.EBOOKS, f"Lös fil ({suffix})"
        if suffix not in COMIC_EXTENSIONS:
            return None, f"Okänt filformat: {suffix or '(inget)'}"
        extensions = {suffix}
        archive_candidate: tuple[Path, BookFormat] | None = (
            path,
            {".cbz": BookFormat.CBZ, ".cbr": BookFormat.CBR}.get(suffix, BookFormat.CB7),
        )
    else:
        extensions = _collect_extensions(path)
        archive_candidate = _first_comic_archive(path)

    if extensions and extensions <= BOOK_EXTENSIONS:
        return LibraryType.EBOOKS, "Endast bok-format (pdf/epub), inga bildarkiv"

    if extensions & COMIC_EXTENSIONS:
        if archive_candidate:
            archive_path, file_format = archive_candidate
            try:
                info = _extract_comicinfo(archive_path, file_format)
            except Exception:  # noqa: BLE001 — a malformed archive shouldn't break classification
                info = {}
            manga_field = (info.get("manga") or "").strip().lower()
            if manga_field in ("yes", "yesandrighttoleft"):
                return LibraryType.MANGA, f"ComicInfo.xml: Manga={info['manga']}"
            if manga_field == "no":
                return LibraryType.COMICS, "ComicInfo.xml: Manga=No"
        detected, reason = _classify_by_name(_candidate_names(path))
        if detected:
            return detected, reason
        return None, "Bildarkiv (cbz/cbr) utan avgörande ComicInfo.xml-signal eller namnmönster"

    if extensions & archive.IMAGE_EXTENSIONS:
        detected, reason = _classify_by_name(_candidate_names(path))
        if detected:
            return detected, reason
        return None, "Lösa bildfiler utan ComicInfo.xml — kan vara serie eller manga"

    if not extensions:
        return None, "Tom mapp eller inga läsbara filer hittades"

    return None, f"Blandat/okänt filinnehåll: {', '.join(sorted(extensions))}"
