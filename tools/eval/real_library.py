"""Evaluates the matching engine on a real library, locally.

Run it against a COPY of a Kodex database with the libraries mounted
read-only: it scans (which parses names and reads embedded metadata),
optionally switches the grouping strategy, matches every series with the
live providers, recording every response into --record-dir, and writes a
report into --out. Both directories must be outside the repository:
recorded responses and library contents are never committed (see
docs/testing.md).

    DATABASE_URL=... python tools/eval/real_library.py --libraries-root /libraries \\
        --record-dir /private/recordings --out /private/eval [--grouping metadata] [--limit 50]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from sqlalchemy import select

from app.models.library import Library
from app.models.series import Series
from app.scanning import scanner
from kodex.core.db import SessionLocal, engine
from kodex.core.migrate import upgrade_database
from kodex.matching.engine import Matcher, build_providers, library_kind
from kodex.matching.models import MatchReview
from kodex.matching.providers.base import RateLimited, RecordingTransport
from kodex.matching.series_ops import accept_regroup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--libraries-root", type=Path, required=True)
    parser.add_argument("--record-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--grouping", choices=["folder", "metadata", "comicvine"])
    parser.add_argument("--library", action="append", help="only these library names")
    parser.add_argument("--limit", type=int, default=0, help="at most this many series per library")
    parser.add_argument("--no-scan", action="store_true")
    parser.add_argument(
        "--accept-regroups", action="store_true", help="accept every regroup proposal (only on a copy!)"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    upgrade_database(engine)
    args.out.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    scanner.get_settings = lambda: type("S", (), {"libraries_root": args.libraries_root, "sorting_auto_apply": False})()  # type: ignore[assignment]
    rows = []
    for library in db.scalars(select(Library).order_by(Library.id)):
        if args.library and library.name not in args.library:
            continue
        if args.grouping:
            library.grouping_strategy = args.grouping
            db.commit()
        if not args.no_scan:
            stats = scanner.scan_library(db, library)
            print(
                f"scanned {library.name}: +{stats.books_added} ~{stats.books_updated} ={stats.books_unchanged}",
                flush=True,
            )
        if args.accept_regroups:
            proposals = list(
                db.scalars(
                    select(MatchReview).where(
                        MatchReview.library_id == library.id,
                        MatchReview.kind == "regroup",
                        MatchReview.status == "open",
                    )
                )
            )
            for review in proposals:
                accept_regroup(db, review)
            db.commit()
            print(f"{library.name}: accepted {len(proposals)} regroup proposals", flush=True)
        kind = library_kind(library)
        providers = build_providers(
            engine, kind, transport_factory=lambda name, secrets: RecordingTransport(args.record_dir / name, secrets)
        )
        matcher = Matcher(db, providers, libraries_root=args.libraries_root)
        series_list = list(db.scalars(select(Series).where(Series.library_id == library.id).order_by(Series.id)))
        if args.limit:
            series_list = series_list[: args.limit]
        for index, series in enumerate(series_list, 1):
            v1_cv = series.comicvine_volume_id
            try:
                outcome = matcher.match_series(series, force=True)
                db.commit()
            except RateLimited as exc:
                db.rollback()
                print(f"rate limited until {exc.retry_at}; stopping", flush=True)
                break
            decision = outcome.decision
            best = decision.best
            ranked = [c.as_dict() for c in decision.ranked[:3]]
            rows.append({
                "library": library.name, "series_id": series.id, "title": series.title, "books": len(series.books),
                "outcome": decision.outcome, "via": outcome.via, "reason": decision.reason, "margin": decision.margin,
                "best": ranked[0] if ranked else None, "others": ranked[1:], "v1_comicvine": v1_cv,
                "agrees_with_v1": (best is not None and v1_cv is not None and any(
                    (m.provider == "comicvine" and m.id == str(v1_cv)) or m.links.get("comicvine") == str(v1_cv)
                    for m in (best.members or [best.run]))) if v1_cv else None,
            })  # fmt: skip
            if index % 10 == 0:
                print(f"{library.name}: {index}/{len(series_list)}", flush=True)
        providers.close()
    (args.out / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
    summary: dict[str, Counter[str]] = {}
    for row in rows:
        summary.setdefault(row["library"], Counter())[row["outcome"]] += 1
        if row["agrees_with_v1"] is not None:
            summary[row["library"]]["v1_" + ("agree" if row["agrees_with_v1"] else "differ")] += 1
    print(json.dumps({k: dict(v) for k, v in summary.items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
