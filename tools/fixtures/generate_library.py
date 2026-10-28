"""Generates a synthetic Kodex library: comics, manga and e-books with
drawn pages, realistic (and deliberately messy) folder and file names,
optional embedded metadata, and a manifest.json with the ground truth for
every file.

    python tools/fixtures/generate_library.py --out /tmp/lib --files 2000

Everything is invented (titles, people, publishers), so the output can be
committed, shared and benchmarked freely. The same --seed always gives the
same library. Layout under --out:

    serier/<Series> (<year>)/...   comics: issues, annuals, TPBs, image folders
    manga/<Title>/...              manga: volumes and chapters, scanlation names
    bocker/<Author>/...            e-books: EPUB (with OPF metadata) and PDF
    manifest.json                  one entry per file, see Entry below

CBR is not generated: creating RAR needs the proprietary `rar` tool (see
backend/tests/fixtures/cbr/ for prebuilt ones).
"""

from __future__ import annotations

import argparse
import io
import itertools
import json
import os
import random
import time
import uuid
import zipfile
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

# --- Invented vocabulary ------------------------------------------------------

_ADJECTIVES = [
    "Crimson",
    "Silent",
    "Iron",
    "Hollow",
    "Neon",
    "Last",
    "Burning",
    "Frozen",
    "Hidden",
    "Golden",
    "Midnight",
    "Savage",
    "Broken",
    "Electric",
    "Lunar",
    "Wandering",
    "Shattered",
    "Velvet",
    "Feral",
    "Copper",
]
_NOUNS = [
    "Harbor",
    "Patrol",
    "Circuit",
    "Lantern",
    "Kingdom",
    "Signal",
    "Orchard",
    "Engine",
    "Tide",
    "Compass",
    "Sentinel",
    "Archive",
    "Garden",
    "Frontier",
    "Mirror",
    "Atlas",
    "Requiem",
    "Beacon",
    "Hollow",
    "Spire",
]
_MANGA_WORDS = [
    "Hoshi",
    "Kaze",
    "Yoru",
    "Sora",
    "Tsuki",
    "Hana",
    "Kumo",
    "Mizu",
    "Ryuu",
    "Akari",
    "Kage",
    "Yuki",
    "Hikari",
    "Umi",
    "Tora",
    "Shiro",
    "Kuro",
    "Mori",
    "Ame",
    "Hotaru",
]
_MANGA_SUFFIXES = ["no Kiseki", "Monogatari", "Senki", "no Uta", "Gakuen", "Tensei", "no Mori", "Days"]
_CJK_TITLES = ["星の旅人", "夜明けの剣", "海辺の図書館", "月下の約束", "風の記憶", "銀河鉄道の夢"]
_FIRST_NAMES = ["Ada", "Bo", "Cleo", "Dag", "Esme", "Finn", "Greta", "Hugo", "Ines", "Jon", "Kaia", "Leo"]
_LAST_NAMES = ["Alder", "Brook", "Corvin", "Dunmore", "Ekholm", "Falk", "Granlund", "Hale", "Ivers", "Juno"]
_PUBLISHERS = ["Northwind Comics", "Bright Harbor Press", "Atlas Lane Publishing", "Red Kite Inc."]
_MANGA_PUBLISHERS = ["Hoshizora Shoten", "Kumo Media", "Tsukiyo Press"]
_SCAN_GROUPS = ["Lumen Scans", "Night Owl", "Paper Crane", "Kitsune TL"]
_TAGS = ["(Digital)", "(Webrip)", "(c2c)", "(digital-Empire)", "(F)", ""]
_COMIC_SUBTITLES = ["Rising", "Legacy", "Unlimited", "Chronicles", "of the North", "Reborn", "Origins", "Forever"]


def _title_pool(rng: random.Random, base: list[str], extensions: list[str]) -> Iterator[str]:
    """Endless unique titles: the base titles in random order, then each
    with an extension appended, then numbered ("... 2", "... 3") forever,
    so even a 50 000-file library never runs out."""
    titles = list(base)
    rng.shuffle(titles)
    yield from titles
    extended = [f"{t} {e}" for t in base for e in extensions if not t.endswith(e)]
    rng.shuffle(extended)
    yield from extended
    for n in itertools.count(2):
        yield from (f"{t} {n}" for t in extended)


@dataclass
class Entry:
    """Ground truth for one generated file (or image folder)."""

    path: str  # relative to --out
    library: str  # comics | manga | ebooks
    file_format: str  # cbz | image_folder | epub | pdf
    series: str | None = None
    series_year: int | None = None
    format: str = "issue"  # issue | annual | collected | volume | chapter | book
    number: str | None = None
    volume: int | None = None
    chapter: str | None = None
    year: int | None = None
    publisher: str | None = None
    scan_group: str | None = None
    has_comicinfo: bool = False
    isbn: str | None = None
    authors: list[str] = field(default_factory=list)
    pages: int = 0


@dataclass
class _Job:
    entry: Entry
    seed: int
    comicinfo: str | None = None
    title: str | None = None
    language: str = "en"


# --- Page drawing -------------------------------------------------------------


def _draw_page(rng: random.Random, label: str, size: tuple[int, int], cover: bool) -> bytes:
    width, height = size
    background = tuple(rng.randint(200, 255) for _ in range(3))
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    if cover:
        # Bold, book-specific shapes so covers differ under perceptual hashing.
        for _ in range(6):
            x0, y0 = rng.randint(0, width), rng.randint(0, height)
            x1, y1 = rng.randint(0, width), rng.randint(0, height)
            box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            draw.ellipse(box, fill=tuple(rng.randint(0, 200) for _ in range(3)))
    else:
        # A simple panel grid with a gutter, like a real comic page.
        rows, cols = rng.choice([(3, 2), (2, 2), (4, 1), (3, 3)])
        gutter = 12
        cell_w, cell_h = (width - gutter) // cols, (height - gutter) // rows
        for r in range(rows):
            for c in range(cols):
                box = (gutter + c * cell_w, gutter + r * cell_h, (c + 1) * cell_w, (r + 1) * cell_h)
                draw.rectangle(box, outline=(20, 20, 20), width=3, fill=tuple(rng.randint(150, 250) for _ in range(3)))
    draw.rectangle((0, height - 40, width, height), fill=(0, 0, 0))
    draw.text((10, height - 32), label, fill=(255, 255, 255))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=70)
    return out.getvalue()


def _pages(job: _Job, size: tuple[int, int]) -> list[bytes]:
    rng = random.Random(job.seed)
    label = f"{job.entry.series or job.title} {job.entry.number or job.entry.chapter or job.entry.volume or ''}".strip()
    return [_draw_page(rng, f"{label} p{i + 1}", size, cover=i == 0) for i in range(job.entry.pages)]


# --- Writers ----------------------------------------------------------------


def _write_cbz(target: Path, job: _Job, size: tuple[int, int]) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as zf:
        for i, page in enumerate(_pages(job, size)):
            zf.writestr(f"{i + 1:03d}.jpg", page)
        if job.comicinfo:
            zf.writestr("ComicInfo.xml", job.comicinfo)


def _write_image_folder(target: Path, job: _Job, size: tuple[int, int]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for i, page in enumerate(_pages(job, size)):
        (target / f"{i + 1:03d}.jpg").write_bytes(page)


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _write_epub(target: Path, job: _Job, size: tuple[int, int]) -> None:
    entry = job.entry
    rng = random.Random(job.seed)
    identifier = f"urn:isbn:{entry.isbn}" if entry.isbn else f"urn:uuid:{uuid.UUID(int=rng.getrandbits(128))}"
    series_meta = ""
    if entry.series:
        series_meta = (
            f'<meta name="calibre:series" content="{_xml_escape(entry.series)}"/>'
            f'<meta name="calibre:series_index" content="{entry.number}"/>'
        )
    chapters = [
        " ".join(rng.choice(_NOUNS + _ADJECTIVES).lower() for _ in range(rng.randint(60, 120))) for _ in range(3)
    ]
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{identifier}</dc:identifier>
    <dc:title>{_xml_escape(job.title or "")}</dc:title>
    {"".join(f"<dc:creator>{_xml_escape(a)}</dc:creator>" for a in entry.authors)}
    <dc:language>{job.language}</dc:language>
    <dc:publisher>{_xml_escape(entry.publisher or "")}</dc:publisher>
    <dc:date>{entry.year}</dc:date>
    <meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>
    {series_meta}
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="cover" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>
    {"".join(f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(len(chapters)))}
  </manifest>
  <spine>{"".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))}</spine>
</package>
"""
    nav = (
        '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol>'
        + "".join(f'<li><a href="c{i}.xhtml">Chapter {i + 1}</a></li>' for i in range(len(chapters)))
        + "</ol></nav></body></html>"
    )
    with zipfile.ZipFile(target, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
            "</container>",
        )
        zf.writestr("content.opf", opf)
        zf.writestr("nav.xhtml", nav)
        zf.writestr("cover.jpg", _draw_page(rng, job.title or "", size, cover=True))
        for i, text in enumerate(chapters):
            zf.writestr(
                f"c{i}.xhtml",
                f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head>'
                f"<title>Chapter {i + 1}</title></head><body><h1>Chapter {i + 1}</h1><p>{text}</p></body></html>",
            )


def _write_pdf(target: Path, job: _Job, size: tuple[int, int]) -> None:
    images = [Image.open(io.BytesIO(page)) for page in _pages(job, size)]
    images[0].save(
        target,
        "PDF",
        save_all=True,
        append_images=images[1:],
        title=job.title or "",
        author=", ".join(job.entry.authors),
    )


_WRITERS = {"cbz": _write_cbz, "image_folder": _write_image_folder, "epub": _write_epub, "pdf": _write_pdf}


def _write(args: tuple[Path, _Job, tuple[int, int]]) -> None:
    out, job, size = args
    target = out / job.entry.path
    target.parent.mkdir(parents=True, exist_ok=True)
    _WRITERS[job.entry.file_format](target, job, size)


# --- Library plan -------------------------------------------------------------


def _comicinfo(entry: Entry, *, manga: bool, web: str | None, title: str | None = None) -> str:
    fields = {
        "Series": entry.series,
        "Title": title,
        "Number": entry.number if entry.format != "volume" else None,
        "Volume": entry.volume if entry.volume is not None else entry.series_year,
        "Year": entry.year,
        "Publisher": entry.publisher,
        "Format": {"annual": "Annual", "collected": "TPB"}.get(entry.format),
        "PageCount": entry.pages,
        "Manga": "YesAndRightToLeft" if manga else None,
        "Web": web,
        "ScanInformation": entry.scan_group,
    }
    body = "".join(f"  <{k}>{_xml_escape(str(v))}</{k}>\n" for k, v in fields.items() if v not in (None, ""))
    return f'<?xml version="1.0" encoding="utf-8"?>\n<ComicInfo>\n{body}</ComicInfo>\n'


def _isbn13(rng: random.Random) -> str:
    digits = [9, 7, 8] + [rng.randint(0, 9) for _ in range(9)]
    check = (10 - sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits)) % 10) % 10
    return "".join(map(str, digits + [check]))


def _comic_jobs(rng: random.Random, budget: int, pages: int) -> list[_Job]:
    jobs: list[_Job] = []
    titles = _title_pool(rng, [f"{a} {n}" for a in _ADJECTIVES for n in _NOUNS], _COMIC_SUBTITLES)
    while len(jobs) < budget:
        title = next(titles)
        publisher = rng.choice(_PUBLISHERS)
        # Same title, several runs (like a relaunch): the matching engine's
        # hardest comic case.
        for start_year in sorted(rng.sample(range(1975, 2025), k=rng.choice([1, 1, 1, 2, 3]))):
            folder = f"serier/{title} ({start_year})"
            style = rng.choice(["scene", "plain", "hash", "volume"])
            tagged = rng.random() < 0.5
            for n in range(1, rng.randint(3, 14) + 1):
                if len(jobs) >= budget:
                    break
                year = start_year + (n - 1) // 12
                tag = rng.choice(_TAGS)
                name = {
                    "scene": f"{title} {n:03d} ({year}) {tag}".strip(),
                    "plain": f"{title} {n:03d}",
                    "hash": f"{title} #{n} (of 12)" if start_year % 2 else f"{title} #{n}",
                    "volume": f"{title} v{start_year % 7 + 1} {n:03d}",
                }[style]
                entry = Entry(
                    path="",
                    library="comics",
                    file_format="cbz",
                    series=title,
                    series_year=start_year,
                    number=str(n),
                    year=year,
                    publisher=publisher,
                    has_comicinfo=tagged,
                    pages=pages,
                )
                web = f"https://comicvine.example/{title.lower().replace(' ', '-')}/4000-{rng.randint(10**5, 10**6)}/"
                as_folder = rng.random() < 0.05
                entry.file_format = "image_folder" if as_folder else "cbz"
                entry.path = f"{folder}/{name}" + ("" if as_folder else ".cbz")
                ci = (
                    _comicinfo(entry, manga=False, web=web if rng.random() < 0.3 else None)
                    if tagged and not as_folder
                    else None
                )
                entry.has_comicinfo = ci is not None
                jobs.append(_Job(entry=entry, seed=rng.getrandbits(32), comicinfo=ci))
            if len(jobs) < budget and rng.random() < 0.3:
                entry = Entry(
                    path=f"{folder}/{title} Annual {start_year + 1} ({start_year + 1}).cbz",
                    library="comics",
                    file_format="cbz",
                    series=title,
                    series_year=start_year,
                    format="annual",
                    number="1",
                    year=start_year + 1,
                    publisher=publisher,
                    pages=pages,
                )
                jobs.append(_Job(entry=entry, seed=rng.getrandbits(32)))
            if len(jobs) < budget and rng.random() < 0.25:
                vol = rng.randint(1, 3)
                entry = Entry(
                    path=f"{folder}/{title} Vol. {vol:02d} - {rng.choice(_NOUNS)} ({start_year + vol}) (TPB).cbz",
                    library="comics",
                    file_format="cbz",
                    series=title,
                    series_year=start_year,
                    format="collected",
                    volume=vol,
                    year=start_year + vol,
                    publisher=publisher,
                    pages=pages + 2,
                )
                ci = _comicinfo(entry, manga=False, web=None) if rng.random() < 0.5 else None
                entry.has_comicinfo = ci is not None
                jobs.append(_Job(entry=entry, seed=rng.getrandbits(32), comicinfo=ci))
    return jobs


def _manga_jobs(rng: random.Random, budget: int, pages: int) -> list[_Job]:
    jobs: list[_Job] = []
    titles = _title_pool(rng, [f"{w} {s}" for w in _MANGA_WORDS for s in _MANGA_SUFFIXES] + _CJK_TITLES, _MANGA_WORDS)
    while len(jobs) < budget:
        title = next(titles)
        publisher = rng.choice(_MANGA_PUBLISHERS)
        start_year = rng.randint(1990, 2025)
        group = rng.choice(_SCAN_GROUPS)
        style = rng.choice(["volumes", "chapters", "scanlation"])
        chapter = 0
        for volume in range(1, rng.randint(2, 8) + 1):
            if len(jobs) >= budget:
                break
            if style == "volumes":
                entry = Entry(
                    path=f"manga/{title}/{title} v{volume:02d}.cbz",
                    library="manga",
                    file_format="cbz",
                    series=title,
                    series_year=start_year,
                    format="volume",
                    volume=volume,
                    year=start_year + volume // 3,
                    publisher=publisher,
                    pages=pages,
                )
                ci = _comicinfo(entry, manga=True, web=None) if rng.random() < 0.5 else None
                entry.has_comicinfo = ci is not None
                jobs.append(_Job(entry=entry, seed=rng.getrandbits(32), comicinfo=ci, language="ja"))
                continue
            for _ in range(rng.randint(3, 6)):
                if len(jobs) >= budget:
                    break
                chapter += 1
                number = f"{chapter}.5" if rng.random() < 0.05 else str(chapter)
                with_volume = rng.random() < 0.7
                if style == "scanlation":
                    name = (
                        f"[{group}] {title} - c{chapter:03d}"
                        + (f" (v{volume:02d})" if with_volume else "")
                        + " [Digital]"
                    )
                else:
                    name = f"{title} " + (f"Vol.{volume} " if with_volume else "") + f"Ch.{number}"
                entry = Entry(
                    path=f"manga/{title}/{name}.cbz",
                    library="manga",
                    file_format="cbz",
                    series=title,
                    series_year=start_year,
                    format="chapter",
                    chapter=number,
                    volume=volume if with_volume else None,
                    publisher=publisher,
                    scan_group=group if style == "scanlation" else None,
                    pages=pages,
                )
                jobs.append(_Job(entry=entry, seed=rng.getrandbits(32), language="ja"))
    return jobs


def _ebook_jobs(rng: random.Random, budget: int) -> list[_Job]:
    jobs: list[_Job] = []
    while len(jobs) < budget:
        author = f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"
        series = f"The {rng.choice(_NOUNS)} Cycle" if rng.random() < 0.4 else None
        for i in range(1, (rng.randint(2, 5) if series else 1) + 1):
            if len(jobs) >= budget:
                break
            title = f"{rng.choice(['The', 'A'])} {rng.choice(_ADJECTIVES)} {rng.choice(_NOUNS)}"
            file_format = "pdf" if rng.random() < 0.15 else "epub"
            entry = Entry(
                path=f"bocker/{author}/{title}{f' ({series} {i})' if series else ''}.{file_format}",
                library="ebooks",
                file_format=file_format,
                series=series,
                format="book",
                number=str(i) if series else None,
                year=rng.randint(1950, 2025),
                publisher=rng.choice(_PUBLISHERS),
                authors=[author],
                isbn=_isbn13(rng) if file_format == "epub" and rng.random() < 0.7 else None,
                pages=3 if file_format == "pdf" else 0,
            )
            jobs.append(_Job(entry=entry, seed=rng.getrandbits(32), title=title, language=rng.choice(["en", "sv"])))
    return jobs


def plan_library(files: int, seed: int, pages: int) -> list[_Job]:
    rng = random.Random(seed)
    comics = int(files * 0.6)
    manga = int(files * 0.25)
    jobs = _comic_jobs(rng, comics, pages) + _manga_jobs(rng, manga, pages)
    jobs += _ebook_jobs(rng, files - len(jobs))
    # Paths must be unique; a rare collision just gets a suffix.
    seen: set[str] = set()
    for job in jobs:
        path = job.entry.path
        while path in seen:
            stem, dot, ext = path.rpartition(".") if "." in Path(path).name else (path, "", "")
            path = f"{stem} (2).{ext}" if dot else f"{path} (2)"
        seen.add(path)
        job.entry.path = path
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--files", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--pages", type=int, default=3, help="pages per comic/manga book")
    parser.add_argument("--page-size", default="400x600", help="WIDTHxHEIGHT of drawn pages")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()

    size = tuple(int(v) for v in args.page_size.split("x"))
    started = time.monotonic()
    jobs = plan_library(args.files, args.seed, args.pages)
    args.out.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(_write, ((args.out, job, size) for job in jobs), chunksize=32))
    manifest = {"seed": args.seed, "files": len(jobs), "entries": [asdict(job.entry) for job in jobs]}
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"Wrote {len(jobs)} files to {args.out} in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
