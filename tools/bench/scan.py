"""Measures the scanner on a library from tools/fixtures/generate_library.py
(docs/plan.sv.md, phase 2 gate): a first scan of every file, then a scan of
the unchanged library. Run it against an empty database:

    DATABASE_URL=postgresql+psycopg://... python tools/bench/scan.py --root /tmp/lib50k

Everything runs as in a real scan: embedded metadata, names, grouping,
both ids. SCAN_WORKERS sets the process pool, as for the server.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.models.enums import LibraryType
from app.models.library import Library
from app.scanning import scanner
from kodex.core.db import SessionLocal, engine
from kodex.core.migrate import upgrade_database

_LIBRARIES = (("serier", LibraryType.COMICS), ("manga", LibraryType.MANGA), ("bocker", LibraryType.EBOOKS))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--rescans", type=int, default=1)
    args = parser.parse_args()

    upgrade_database(engine)
    workers = int(os.environ.get("SCAN_WORKERS", "0") or 0)
    scanner.get_settings = lambda: SimpleNamespace(
        libraries_root=args.root, sorting_auto_apply=False, scan_workers=workers
    )  # type: ignore[assignment]
    db = SessionLocal()
    libraries = []
    for path, kind in _LIBRARIES:
        if (args.root / path).is_dir():
            library = Library(name=path, path=path, library_type=kind)
            db.add(library)
            libraries.append(library)
    db.commit()

    def scan_all() -> tuple[float, int]:
        started, books = time.perf_counter(), 0
        for library in libraries:
            stats = scanner.scan_library(db, library)
            db.commit()
            books += stats.books_added + stats.books_updated + stats.books_unchanged
        return time.perf_counter() - started, books

    first, books = scan_all()
    report = {"books": books, "first_scan_s": round(first, 1), "files_per_s": round(books / first, 1)}
    for i in range(args.rescans):
        report[f"rescan_{i + 1}_s"] = round(scan_all()[0], 1)
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
