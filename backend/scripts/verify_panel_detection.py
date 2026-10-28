"""Manual verification tool for Guided View panel detection — run this
against a handful of real books before trusting a library-wide
POST /libraries/{id}/detect-panels run (see app/panels/detector.py's
module docstring for why: the heuristic has real, disclosed failure modes,
and this is how they were found and tuned against actual pages from this
library in the first place).

Usage (inside the api or worker container, which have the real DB and
LIBRARIES_ROOT mounted — this is a one-off dev tool, not an app endpoint):

    python -m scripts.verify_panel_detection <book_id> [page_index ...]
    python -m scripts.verify_panel_detection <book_id> --all

Writes one annotated PNG per requested page (red boxes = detected panels,
numbered in reading order) next to a printed summary, into
--out-dir (default: /tmp/panel-verify/<book_id>/). Doesn't touch the
database — read-only, safe to run against production.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

from app.config import get_settings
from app.database import SessionLocal
from app.models.book import Book
from app.models.enums import BookFormat
from app.panels.detector import detect_panels
from app.scanning import archive


def _page_image_path(book: Book, page_index: int, cache_dir: Path) -> Path:
    settings = get_settings()
    absolute_path = settings.libraries_root / book.library.path / book.file_path

    if book.file_format == BookFormat.IMAGE_FOLDER:
        images = sorted(p for p in absolute_path.iterdir() if p.suffix.lower() in archive.IMAGE_EXTENSIONS)
        return images[page_index]

    return archive.extract_page(absolute_path, book.file_format, page_index, cache_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("book_id", type=int)
    parser.add_argument("pages", nargs="*", type=int, help="Page indices to check (default: first 10)")
    parser.add_argument("--all", action="store_true", help="Check every page in the book")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    db = SessionLocal()
    book = db.get(Book, args.book_id)
    if book is None:
        print(f"No book with id={args.book_id}", file=sys.stderr)
        sys.exit(1)

    if book.file_format not in (BookFormat.CBZ, BookFormat.CBR, BookFormat.IMAGE_FOLDER):
        print(f"Book {args.book_id} is {book.file_format.value}, not page-based — nothing to check", file=sys.stderr)
        sys.exit(1)

    if args.all:
        page_indices = range(book.page_count or 0)
    elif args.pages:
        page_indices = args.pages
    else:
        page_indices = range(min(10, book.page_count or 0))

    settings = get_settings()
    cache_dir = settings.covers_dir / "pages" / str(book.id)
    out_dir = args.out_dir or Path(f"/tmp/panel-verify/{book.id}")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Book {book.id}: {book.file_path} ({book.file_format.value}, {book.page_count} pages)")
    for page_index in page_indices:
        page_path = _page_image_path(book, page_index, cache_dir)
        panels = detect_panels(page_path)
        print(f"  page {page_index}: {len(panels)} panel(s)")

        img = cv2.imread(str(page_path))
        h, w = img.shape[:2]
        for i, panel in enumerate(panels):
            x1, y1 = int(panel.x * w), int(panel.y * h)
            x2, y2 = int((panel.x + panel.w) * w), int((panel.y + panel.h) * h)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 8)
            cv2.putText(img, str(i), (x1 + 10, y1 + 60), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 4)
        out_path = out_dir / f"page-{page_index:04d}.jpg"
        cv2.imwrite(str(out_path), img)

    print(f"Annotated pages written to {out_dir}")
    db.close()


if __name__ == "__main__":
    main()
