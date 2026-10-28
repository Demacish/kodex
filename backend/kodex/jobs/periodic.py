"""Periodic jobs, deduplicated by Procrastinate in the database however
many workers run:

- every ten minutes, libraries not scanned for ``rescan_interval_minutes``
  are scanned (the polling that network shares need, where file events
  don't arrive; an unchanged library rescans in seconds);
- every Monday morning, followed series are checked for new releases;
- every quarter of an hour, what was read in series linked to trackers is
  sent to them;
- every two minutes, with the acquisition add-on on, the download clients
  are asked about its downloads, and finished ones are imported;
- every night at 03:30, the database is dumped to /data/backups;
- every night, jobs that ended more than ``job_retention_days`` ago are
  removed with their results, and so are expired sessions, old failed
  logins and abandoned OpenID Connect logins.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import or_, select, text

from kodex.jobs.app import app
from kodex.jobs.queue import DOWNLOAD_QUEUE_NAME, ENRICHMENT_QUEUE_NAME, SCAN_QUEUE_NAME


def due_libraries(now: dt.datetime, interval: dt.timedelta) -> list[int]:
    from app.models.library import Library
    from kodex.core.db import SessionLocal

    with SessionLocal() as db:
        return list(
            db.scalars(
                select(Library.id).where(
                    or_(Library.last_scanned_at.is_(None), Library.last_scanned_at < now - interval)
                )
            )
        )


@app.periodic(cron="*/10 * * * *", periodic_id="poll-libraries")
@app.task(name="poll_libraries", queue=SCAN_QUEUE_NAME, queueing_lock="poll_libraries")
def poll_libraries(timestamp: int) -> int:
    from app.config import get_settings
    from app.workers.queue import get_scan_queue
    from app.workers.tasks import scan_library_task

    minutes = get_settings().rescan_interval_minutes
    if minutes <= 0:
        return 0
    due = due_libraries(dt.datetime.fromtimestamp(timestamp, dt.UTC), dt.timedelta(minutes=minutes))
    for library_id in due:
        get_scan_queue().enqueue(scan_library_task, library_id, job_id=f"scan-library-{library_id}")
    return len(due)


@app.periodic(cron="0 6 * * 1", periodic_id="release-check")
@app.task(name="periodic_release_check", queue=ENRICHMENT_QUEUE_NAME, queueing_lock="periodic_release_check")
def release_check(timestamp: int) -> None:
    from app.workers.queue import get_enrichment_queue
    from app.workers.tasks import check_followed_series_task

    get_enrichment_queue().enqueue(check_followed_series_task, job_id="check-followed-series")


def remove_old_jobs_before(cutoff: dt.datetime) -> int:
    from kodex.core.db import engine

    with engine.begin() as connection:
        ids = [
            row[0]
            for row in connection.execute(
                text(
                    "SELECT j.id FROM procrastinate_jobs j WHERE j.status IN ('succeeded', 'failed', 'cancelled', 'aborted') "
                    "AND NOT EXISTS (SELECT 1 FROM procrastinate_events e WHERE e.job_id = j.id AND e.at >= :cutoff)"
                ),
                {"cutoff": cutoff},
            )
        ]
        if ids:
            connection.execute(text("DELETE FROM job_results WHERE job_id = ANY(:ids)"), {"ids": ids})
            connection.execute(text("DELETE FROM procrastinate_jobs WHERE id = ANY(:ids)"), {"ids": ids})
    return len(ids)


@app.periodic(cron="30 3 * * *", periodic_id="remove-old-jobs")
@app.task(name="remove_old_jobs", queue=SCAN_QUEUE_NAME, queueing_lock="remove_old_jobs")
def remove_old_jobs(timestamp: int) -> int:
    from app.config import get_settings

    days = get_settings().job_retention_days
    return remove_old_jobs_before(dt.datetime.fromtimestamp(timestamp, dt.UTC) - dt.timedelta(days=days))


@app.periodic(cron="50 3 * * *", periodic_id="compact-reading-journal")
@app.task(name="compact_reading_journal", queue=SCAN_QUEUE_NAME, queueing_lock="compact_reading_journal")
def compact_reading_journal(timestamp: int) -> int:
    from app.config import get_settings
    from kodex.core.db import SessionLocal
    from kodex.reading import journal

    before = dt.datetime.fromtimestamp(timestamp, dt.UTC) - dt.timedelta(days=get_settings().reading_journal_days)
    with SessionLocal() as db:
        removed = journal.compact(db, before)
        db.commit()
    return removed


@app.periodic(cron="55 3 * * *", periodic_id="compact-sync-log")
@app.task(name="compact_sync_log", queue=SCAN_QUEUE_NAME, queueing_lock="compact_sync_log")
def compact_sync_log(timestamp: int) -> int:
    from kodex.core import sync
    from kodex.core.db import SessionLocal

    with SessionLocal() as db:
        removed = sync.compact(db)
        db.commit()
    return removed


@app.periodic(cron="40 3 * * *", periodic_id="remove-expired-logins")
@app.task(name="remove_expired_logins", queue=SCAN_QUEUE_NAME, queueing_lock="remove_expired_logins")
def remove_expired_logins(timestamp: int) -> int:
    from kodex.core.auth import factors, links, oidc, sessions, throttle
    from kodex.core.db import SessionLocal

    now = dt.datetime.fromtimestamp(timestamp, dt.UTC)
    with SessionLocal() as db:
        removed = (sessions.remove_expired(db, now) + throttle.remove_old(db, now) + oidc.remove_stale(db, now)
                   + factors.remove_stale(db, now) + links.remove_expired(db, now))  # fmt: skip
        db.commit()
    return removed


@app.periodic(cron="*/15 * * * *", periodic_id="push-trackers")
@app.task(name="push_trackers", queue=ENRICHMENT_QUEUE_NAME, queueing_lock="push_trackers")
def push_trackers(timestamp: int) -> int:
    """What was read in linked series, to the users' trackers (kodex.reading.trackers)."""
    from kodex.core.db import SessionLocal
    from kodex.reading.trackers.push import push_all

    with SessionLocal() as db:
        return push_all(db)


@app.periodic(cron="*/2 * * * *", periodic_id="poll-downloads")
@app.task(name="poll_downloads", queue=DOWNLOAD_QUEUE_NAME, queueing_lock="poll_downloads")
def poll_downloads(timestamp: int) -> int:
    """The add-on's downloads in qBittorrent and SABnzbd; finished ones are imported (kodex.acquire)."""
    from kodex.acquire.pipeline import enabled, poll
    from kodex.core.db import SessionLocal

    if not enabled():
        return 0
    with SessionLocal() as db:
        return poll(db)


@app.periodic(cron="30 3 * * *", periodic_id="backup-database")
@app.task(name="backup_database", queue=SCAN_QUEUE_NAME, queueing_lock="backup_database")
def backup_database(timestamp: int) -> str | None:
    """The nightly dump to /data/backups (kodex.core.backup), unless BACKUP_KEEP=0 or there is no pg_dump."""
    import os
    import shutil

    from kodex.core import backup

    if os.environ.get("BACKUP_KEEP", "7").strip() == "0" or shutil.which("pg_dump") is None:
        return None
    return str(backup.dump())
