"""Measures the API on a scanned library (docs/plan.sv.md, phase 7): the
lists, search, OPDS and the apps' delta sync, each called repeatedly in
process. Run it after tools/bench/scan.py, against the same database:

    AUTH_DISABLED=true DATABASE_URL=postgresql+psycopg://... python tools/bench/api.py

Prints one JSON line: per call, the median and the 95th percentile in
milliseconds, and how long a full sync from cursor 0 takes.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models.book import Book
from app.models.library import Library
from app.models.series import Series
from kodex.core.db import SessionLocal

ROUNDS = 20


def timed(client: TestClient, path: str) -> dict[str, float]:
    times = []
    for _ in range(ROUNDS):
        started = time.perf_counter()
        response = client.get(path)
        times.append((time.perf_counter() - started) * 1000)
        if response.status_code != 200:
            raise SystemExit(f"{path}: HTTP {response.status_code} {response.text[:200]}")
    times.sort()
    return {"median_ms": round(statistics.median(times), 1), "p95_ms": round(times[int(len(times) * 0.95) - 1], 1)}


def main() -> int:
    with SessionLocal() as db:
        books = db.scalar(select(func.count()).select_from(Book)) or 0
        library = db.scalars(select(Library).order_by(Library.id)).first()
        series = db.scalars(select(Series).order_by(Series.id)).first()
    if library is None or series is None:
        raise SystemExit("Run tools/bench/scan.py first")
    paths = {
        "books_page": "/api/books?limit=50",
        "books_page_deep": "/api/books?limit=50&offset=20000",
        "series_of_library": f"/api/series?library_id={library.id}&limit=100",
        "series_books": f"/api/books?series_id={series.id}&limit=100",
        "search": "/api/search/books?q=the",
        "search_cjk": "/api/search/books?q=%E3%81%AE",
        "opds_latest": "/opds/latest",
        "opds_v2_latest": "/opds/v2/latest",
        "continue_reading": "/api/me/continue-reading",
    }
    report: dict[str, object] = {"books": books}
    with TestClient(app) as client:
        for name, path in paths.items():
            try:
                report[name] = timed(client, path)
            except SystemExit as exc:
                report[name] = {"error": str(exc)}
        started, pages, cursor, more = time.perf_counter(), 0, 0, True
        while more:
            answer = client.get(f"/api/sync/changes?since={cursor}&progress_since=0&limit=2000").json()
            cursor, more, pages = answer["cursor"], answer["more"], pages + 1
        report["full_sync"] = {"pages": pages, "seconds": round(time.perf_counter() - started, 1)}
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
