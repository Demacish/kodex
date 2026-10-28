"""Database backups: ``python -m kodex.core.backup dump | list | verify FILE | restore FILE``.

- ``dump`` writes ``/data/backups/kodex-<time>.dump`` (pg_dump's custom
  format, compressed) and keeps the newest ``BACKUP_KEEP`` (7). The worker
  also runs it every night at 03:30 unless ``BACKUP_KEEP=0``.
- ``verify FILE`` is the restore drill: it restores the dump into a
  database of its own, compares the row counts of the main tables with
  the live ones, and drops it again.
- ``restore FILE`` replaces the database's contents with the dump's. Stop
  the worker first, then start the api again (it migrates the restored
  schema to head).

pg_dump and pg_restore come with the image, at the server's major version.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

DIRECTORY = Path(os.environ.get("BACKUP_DIR", "/data/backups"))
# The tables a restore drill compares (people's data, not caches).
CHECKED_TABLES = ("users", "libraries", "series", "books", "reading_progress", "collections", "requests")


def _keep() -> int:
    raw = os.environ.get("BACKUP_KEEP", "7").strip()
    return int(raw) if raw.isdigit() else 7


def database_url(name: str | None = None) -> str:
    """The database as libpq wants it (no SQLAlchemy driver suffix), optionally another database on the same server."""
    from kodex.jobs.app import conninfo

    url = conninfo()
    if name is None:
        return url
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


def dumps() -> list[Path]:
    return sorted(DIRECTORY.glob("kodex-*.dump"))


def dump() -> Path:
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    target = DIRECTORY / f"kodex-{dt.datetime.now(dt.UTC):%Y%m%d-%H%M%S}.dump"
    partial = target.with_suffix(".partial")
    subprocess.run(["pg_dump", "--format=custom", "--no-owner", f"--file={partial}", database_url()], check=True)
    partial.rename(target)
    for old in dumps()[: -_keep()] if _keep() else []:
        old.unlink()
    logger.info("Backed up the database to %s", target)
    return target


def _counts(url: str) -> dict[str, int]:
    from sqlalchemy import create_engine, text

    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
    try:
        with engine.connect() as connection:
            return {
                t: int(connection.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() or 0) for t in CHECKED_TABLES
            }
    finally:
        engine.dispose()


def _admin(sql: str) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url("postgres").replace("postgresql://", "postgresql+psycopg://", 1),
                           isolation_level="AUTOCOMMIT")  # fmt: skip
    try:
        with engine.connect() as connection:
            connection.execute(text(sql))
    finally:
        engine.dispose()


def verify(path: Path) -> dict[str, tuple[int, int]]:
    """Restores the dump into ``kodex_restore_check``; the live and restored
    row counts per table. Raises when the restore fails."""
    scratch = "kodex_restore_check"
    _admin(f'DROP DATABASE IF EXISTS "{scratch}"')
    _admin(f'CREATE DATABASE "{scratch}"')
    try:
        subprocess.run(["pg_restore", "--no-owner", "--exit-on-error", f"--dbname={database_url(scratch)}", str(path)],
                       check=True)  # fmt: skip
        live, restored = _counts(database_url()), _counts(database_url(scratch))
    finally:
        _admin(f'DROP DATABASE IF EXISTS "{scratch}"')
    return {t: (live[t], restored[t]) for t in CHECKED_TABLES}


def restore(path: Path) -> None:
    subprocess.run(["pg_restore", "--clean", "--if-exists", "--no-owner", "--exit-on-error",
                    f"--dbname={database_url()}", str(path)], check=True)  # fmt: skip


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    match argv:
        case ["dump"]:
            print(dump())
        case ["list"]:
            for path in dumps():
                print(f"{path}  {path.stat().st_size // 1024} kB")
        case ["verify", file]:
            counts = verify(Path(file))
            for table, (live, restored) in counts.items():
                print(f"{table:20} live {live:8}  restored {restored:8}")
            # A dump is older than the live data, so fewer rows can be right; none at all where there are some isn't.
            if any(live and not restored for live, restored in counts.values()):
                print("The restored database is missing whole tables' rows", file=sys.stderr)
                return 1
        case ["restore", file]:
            restore(Path(file))
        case _:
            print(__doc__, file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
