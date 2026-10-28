"""RQ job bodies. Each job opens its own DB session since it runs in a
separate worker process from the API.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import httpx
from sqlalchemy import func

from app.config import get_settings
from app.database import SessionLocal
from app.enrichment import cbl, leagueofcomicgeeks, metron
from app.enrichment.engine import auto_enrich_book
from app.enrichment.release_check import check_series_for_new_release
from app.enrichment.story_arc_roster import fetch_arc_roster
from app.models.book import Book
from app.models.download import Download
from app.models.enums import BookFormat, DownloadClientType, DownloadStatus, LibraryType, RequestStatus, SortingStatus
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.reading_progress import ReadingProgress
from app.models.request import Request
from app.models.series import Series
from app.models.sorting import SortingItem
from app.models.story_arc import StoryArc, StoryArcIssue
from app.models.user import User
from app.panels.service import detect_panels_for_book
from app.progress import upstream
from app.progress.sync import to_kosync_progress
from app.scanning import archive
from app.scanning.dimensions import cbr_page_dimensions
from app.scanning.scanner import scan_library
from app.search.fulltext import index_library_fulltext
from app.workers.queue import get_enrichment_queue, get_scan_queue
from kodex.acquire.clients.base import DownloadClientError
from kodex.acquire.clients.manager import IMPORTABLE_EXTENSIONS, map_download_path
from kodex.acquire.clients.qbittorrent import QBittorrentClient
from kodex.acquire.clients.sabnzbd import SabnzbdClient
from kodex.acquire.sorting.classifier import classify
from kodex.acquire.sorting.comicinfo_writer import parse_series_and_number, write_comicinfo_to_cbz
from kodex.acquire.sorting.paths import DESTINATION_LIBRARY_PATHS
from kodex.delivery.federation.peers import PeerError, get_peer
from kodex.delivery.kindle import send_book_to_kindle
from kodex.delivery.notify import notify_new_books, notify_new_release

logger = logging.getLogger(__name__)


def scan_library_task(library_id: int) -> dict:
    db = SessionLocal()
    try:
        library = db.get(Library, library_id)
        if library is None:
            raise ValueError(f"Library {library_id} not found")

        # The intake library ("mixed", see kodex/acquire/sorting/): classify new
        # arrivals into the sorting queue, and with SORTING_AUTO_APPLY move
        # the confident ones to their comics/manga/ebooks library — BEFORE
        # scanning, so a moved item never becomes a book in the intake
        # library too (the scanner doesn't remove books whose files left).
        sorting: dict | None = None
        if _is_intake_library(db, library):
            sorting = _sort_intake_on_scan(db, library)

        stats = scan_library(db, library)

        library.last_scanned_at = func.now()
        db.add(library)
        db.commit()

        notified = _notify_new_books_in_followed_series(db, stats.new_book_ids)
        matching_job = _enqueue_matching_of_new_series(db, library, stats.new_book_ids)
        covers_job = None
        if stats.books_added or stats.books_updated:
            queued = get_scan_queue().enqueue(generate_covers_task, library.id, job_id=f"covers-{library.id}")
            covers_job = getattr(queued, "id", None)

        logger.info(
            "Scanned library %s: +%d ~%d =%d (%d errors)",
            library.name,
            stats.books_added,
            stats.books_updated,
            stats.books_unchanged,
            len(stats.errors),
        )
        result = {
            "books_added": stats.books_added,
            "books_updated": stats.books_updated,
            "books_unchanged": stats.books_unchanged,
            "books_hidden": stats.books_hidden,
            "books_restored": stats.books_restored,
            "notifications_sent": notified,
            "errors": stats.errors,
        }
        if sorting is not None:
            result["sorting"] = sorting
        if matching_job is not None:
            result["matching_job_id"] = matching_job
        if covers_job is not None:
            result["covers_job_id"] = covers_job
        return result
    finally:
        db.close()


def generate_covers_task(library_id: int) -> dict:
    """Makes the three cover sizes (kodex.library.covers) for the library's
    books that have none yet; queued after a scan that found new books."""
    from kodex.library.covers import make_missing

    settings = get_settings()
    db = SessionLocal()
    try:
        return {"covers_made": make_missing(db, library_id, settings.libraries_root, settings.covers_dir)}
    finally:
        db.close()


def _enqueue_matching_of_new_series(db, library: Library, new_book_ids: list[int]) -> str | None:
    """New books in series that were never matched start a matching run
    for the library (MATCH_AFTER_SCAN; the intake library is skipped)."""
    from app.models.series import Series

    settings = get_settings()
    if not getattr(settings, "match_after_scan", False) or not new_book_ids or library.library_type.value == "mixed":
        return None
    pending = (
        db.query(Series.id)
        .join(Book, Book.series_id == Series.id)
        .filter(Book.id.in_(new_book_ids), Series.match_status == "unmatched")
        .first()
    )
    if pending is None:
        return None
    try:
        return get_enrichment_queue().enqueue(match_library_task, library.id, False, job_timeout="6h").id
    except Exception:
        logger.exception("Could not enqueue matching for library %s", library.id)
        return None


def _notify_new_books_in_followed_series(db, new_book_ids: list[int]) -> int:
    """Push (ntfy) for new books in followed series — one notification per
    series, to every user with an ntfy topic (following is per household,
    see Series.is_following). Only books this scan added count, so a first
    scan of a library or a book reappearing never notifies. Never fails
    the scan."""
    if not new_book_ids:
        return 0
    try:
        users = db.query(User).filter(User.ntfy_topic.isnot(None)).all()
        if not users:
            return 0
        by_series: dict[int, list[Book]] = {}
        for book in db.query(Book).filter(Book.id.in_(new_book_ids), Book.series_id.isnot(None)).all():
            if book.series.is_following:
                by_series.setdefault(book.series_id, []).append(book)
        settings = get_settings()
        return sum(notify_new_books(books[0].series, books, users, settings=settings) for books in by_series.values())
    except Exception:
        logger.exception("Push notifications for new books failed")
        return 0


def _is_intake_library(db, library: Library) -> bool:
    """The sorting intake is the first "mixed" library by name — the same
    one the admin Sortering page picks (frontend admin/sorting/page.tsx
    takes the first mixed entry of GET /libraries, which is name-ordered).
    Any other mixed library is an ordinary library and is never sorted
    automatically."""
    if library.library_type != LibraryType.MIXED:
        return False
    first_mixed = db.query(Library.id).filter(Library.library_type == LibraryType.MIXED).order_by(Library.name).first()
    return first_mixed is not None and first_mixed[0] == library.id


def _sort_intake_on_scan(db, library: Library) -> dict:
    """See scan_library_task. Never fails the scan itself: a sorting
    problem (most likely the destination libraries not created yet) is
    logged and reported in the job result, and the intake is scanned as
    before."""
    result: dict = {"items_added": 0, "moved": 0, "failed": 0}
    try:
        result["items_added"] = _classify_intake(db, library)
        if get_settings().sorting_auto_apply:
            applied = _apply_resolved_items(db, library)
            result.update(moved=applied["moved"], failed=applied["failed"])
    except Exception as exc:
        db.rollback()
        logger.exception("Automatic sorting of intake library %s failed", library.name)
        result["error"] = str(exc)
    return result


def compute_page_dimensions_task(book_id: int) -> dict:
    """Sizes every page of a CBR (see app/scanning/dimensions.py) — queued
    by GET /books/{id}/pages/dimensions the first time a CBR is opened."""
    db = SessionLocal()
    try:
        book = db.get(Book, book_id)
        if book is None or book.page_dimensions is not None or not book.page_count:
            return {"pages": 0}
        settings = get_settings()
        path = settings.libraries_root / book.library.path / book.file_path
        cache_dir = settings.covers_dir / "pages" / str(book.id)
        book.page_dimensions = cbr_page_dimensions(path, book.page_count, cache_dir, book.file_format)
        db.add(book)
        db.commit()
        return {"pages": len(book.page_dimensions)}
    finally:
        db.close()


def copy_books_to_peer_task(peer_name: str, library_id: int, book_ids: list[int]) -> dict:
    """Copies books to another Kodex server (see kodex/delivery/federation), each into
    its series' folder there, then asks that server for one scan. A file
    that already exists there is skipped, not overwritten. An image-folder
    book goes as a CBZ zipped on the fly (uploads take single files). One
    book failing doesn't stop the rest; the result lists every outcome."""
    peer = get_peer(peer_name)
    if peer is None:
        raise ValueError(f"Unknown server: {peer_name}")
    db = SessionLocal()
    try:
        settings = get_settings()
        outcomes: dict[str, list[str]] = {"copied": [], "exists": [], "failed": []}
        for book in db.query(Book).filter(Book.id.in_(book_ids)).all():
            source = settings.libraries_root / book.library.path / book.file_path
            subfolder = book.series.path if book.series else ""
            label = book.file_path
            try:
                if book.file_format == BookFormat.IMAGE_FOLDER:
                    with tempfile.TemporaryDirectory() as tmp:
                        archive_path = Path(tmp) / f"{source.name}.cbz"
                        _zip_image_folder(source, archive_path)
                        outcome = peer.upload(
                            library_id, archive_path, upload_name=archive_path.name, subfolder=subfolder, rescan=False
                        )
                else:
                    outcome = peer.upload(
                        library_id, source, upload_name=source.name, subfolder=subfolder, rescan=False
                    )
            except (PeerError, OSError) as exc:
                logger.warning("Copying %s to %s failed: %s", label, peer_name, exc)
                outcomes["failed"].append(f"{label}: {exc}")
                continue
            outcomes[outcome].append(label)

        if outcomes["copied"]:
            peer.scan(library_id)
        logger.info(
            "Copied %d book(s) to %s (%d already there, %d failed)",
            len(outcomes["copied"]),
            peer_name,
            len(outcomes["exists"]),
            len(outcomes["failed"]),
        )
        return outcomes
    finally:
        db.close()


def _zip_image_folder(folder: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as zf:
        for page in archive.list_image_folder_pages(folder):
            zf.write(page, arcname=page.name)


def push_progress_upstream_task(book_id: int, user_id: int, reset: bool = False) -> dict:
    """Sends this user's position on one book to the central Kodex server
    (see app/progress/upstream.py). Failures raise so the job shows as
    failed in Admin › Jobb; the next save pushes again anyway."""
    db = SessionLocal()
    try:
        book = db.get(Book, book_id)
        progress = (
            db.query(ReadingProgress)
            .filter(ReadingProgress.book_id == book_id, ReadingProgress.user_id == user_id)
            .one_or_none()
        )
        if book is None or progress is None or not book.content_hash:
            return {"pushed": False}
        upstream.push(
            book.content_hash,
            progress=to_kosync_progress(book, progress),
            percentage=progress.progress_percent / 100,
            reset=reset,
        )
        return {"pushed": True}
    finally:
        db.close()


def match_library_task(library_id: int, force: bool = False) -> dict:
    """Runs the matching engine (kodex.matching) over a library's series
    that still need it (all of them with force)."""
    from kodex.matching.jobs import match_library

    db = SessionLocal()
    try:
        result = match_library(db, library_id, force=force)
        logger.info("Matched library %s: %s", library_id, result)
        return result
    finally:
        db.close()


def match_series_task(series_id: int) -> dict:
    from kodex.matching.jobs import match_one

    db = SessionLocal()
    try:
        return match_one(db, series_id)
    finally:
        db.close()


def enrich_library_task(library_id: int, force: bool = False) -> dict:
    """Enriches every (thin, non-manual — unless force=True) book in one
    library. This is the manually-triggered job behind
    POST /libraries/{id}/enrich; there is no automatic scheduling of it,
    matching how it's specified in the architecture plan.
    """
    db = SessionLocal()
    settings = get_settings()
    try:
        library = db.get(Library, library_id)
        if library is None:
            raise ValueError(f"Library {library_id} not found")

        books = db.query(Book).filter(Book.library_id == library_id).all()
        enriched = 0
        for book in books:
            try:
                if auto_enrich_book(
                    db,
                    book,
                    comicvine_api_key=settings.comicvine_api_key,
                    google_books_api_key=settings.google_books_api_key,
                    metron_username=settings.metron_username,
                    metron_password=settings.metron_password,
                    force=force,
                ):
                    enriched += 1
                    db.commit()
            except Exception:
                logger.exception("Enrichment failed for book %s in library %s", book.id, library_id)
                db.rollback()

        logger.info("Enriched %d/%d books in library %s", enriched, len(books), library.name)
        return {"books_considered": len(books), "books_enriched": enriched}
    finally:
        db.close()


def enrich_book_task(book_id: int, force: bool = True) -> dict:
    """Enriches a single book — used for a one-off "re-enrich this book"
    action from the API, as opposed to the library-wide job above.
    """
    db = SessionLocal()
    settings = get_settings()
    try:
        book = db.get(Book, book_id)
        if book is None:
            raise ValueError(f"Book {book_id} not found")

        changed = auto_enrich_book(
            db,
            book,
            comicvine_api_key=settings.comicvine_api_key,
            google_books_api_key=settings.google_books_api_key,
            metron_username=settings.metron_username,
            metron_password=settings.metron_password,
            force=force,
        )
        db.commit()
        return {"changed": changed}
    finally:
        db.close()


def fulltext_index_library_task(library_id: int) -> dict:
    """Extracts and indexes fulltext for every EPUB/PDF book in one library.
    This is the manually-triggered job behind POST /libraries/{id}/
    fulltext-index — never run automatically on scan, since extracting and
    indexing full book text is far more expensive than metadata indexing
    (see the architecture plan's "Sök och indexering" section).
    """
    db = SessionLocal()
    try:
        library = db.get(Library, library_id)
        if library is None:
            raise ValueError(f"Library {library_id} not found")

        result = index_library_fulltext(db, library)

        library.last_fulltext_indexed_at = func.now()
        db.add(library)
        db.commit()

        logger.info(
            "Fulltext-indexed library %s: %d/%d books, %d entries",
            library.name,
            result["books_indexed"],
            result["books_considered"],
            result["entries_indexed"],
        )
        return result
    finally:
        db.close()


def send_to_kindle_task(book_id: int, user_id: int) -> dict:
    """Background job behind POST /books/{id}/send-to-kindle. Kept off the
    request path (see kodex/delivery/kindle.py's docstring) since converting
    a CBZ/CBR to PDF and then talking to an SMTP server can both take a
    while. A failure here (missing SMTP config, no Kindle address, a
    bounced send) surfaces as a failed RQ job, visible via GET /jobs/{id}.
    """
    db = SessionLocal()
    settings = get_settings()
    try:
        book = db.get(Book, book_id)
        if book is None:
            raise ValueError(f"Book {book_id} not found")

        user = db.get(User, user_id)
        if user is None or not user.kindle_email:
            raise ValueError(f"User {user_id} has no Kindle address set")

        # Duplicated rather than imported from app.api.routes.books: that
        # function is private to the routes module, and the computation
        # itself is a one-liner not worth a shared-module detour for.
        absolute_path = settings.libraries_root / book.library.path / book.file_path
        if not absolute_path.is_file():
            raise ValueError(f"File missing on disk for book {book_id}: {absolute_path}")

        send_book_to_kindle(book, absolute_path, user.kindle_email, settings=settings)
        logger.info("Sent book %s to %s", book_id, user.kindle_email)
        return {"sent": True, "kindle_email": user.kindle_email}
    finally:
        db.close()


def detect_panels_library_task(library_id: int, force: bool = False) -> dict:
    """Runs Guided View panel detection for every page-based (CBZ/CBR/
    image-folder) book in one library. Manually-triggered, same convention
    as enrich_library_task above — no automatic scheduling on scan.
    """
    db = SessionLocal()
    try:
        library = db.get(Library, library_id)
        if library is None:
            raise ValueError(f"Library {library_id} not found")

        books = db.query(Book).filter(Book.library_id == library_id).all()
        processed = 0
        for book in books:
            try:
                if detect_panels_for_book(db, book, force=force):
                    processed += 1
                    db.commit()
                else:
                    db.commit()  # persists UNSUPPORTED/skip status rows too
            except Exception:
                logger.exception("Panel detection failed for book %s in library %s", book.id, library_id)
                db.rollback()

        logger.info("Panel detection: %d/%d books processed in library %s", processed, len(books), library.name)
        return {"books_considered": len(books), "books_processed": processed}
    finally:
        db.close()


def detect_panels_book_task(book_id: int, force: bool = True) -> dict:
    """Detects panels for a single book — used for a one-off "(re)run
    Guided View detection for this book" action, as opposed to the
    library-wide job above.
    """
    db = SessionLocal()
    try:
        book = db.get(Book, book_id)
        if book is None:
            raise ValueError(f"Book {book_id} not found")

        processed = detect_panels_for_book(db, book, force=force)
        db.commit()
        return {"processed": processed}
    finally:
        db.close()


def check_followed_series_task() -> dict:
    """Weekly job (also triggerable on demand via
    POST /series/check-releases from the adminvy): for every series marked
    as followed, see if a newer issue/volume is now published — see
    app/enrichment/release_check.py for how, and its real limitations
    (best-effort, and for RELEASING manga on AniList frequently unable to
    tell at all). Started from the API process, not this worker, by
    kodex.jobs.periodic every Monday — but runs as an ordinary
    enrichment-queue job either way, since it's the same kind of
    metadata-provider network calls as normal enrichment.

    One bad series (a network hiccup, an unexpected provider response)
    must never stop the rest of the sweep — same "isolate failures
    per-item" pattern as enrich_library_task above.

    A series that already had new_release_available=True before this run
    keeps re-appearing in that state every week until someone adds the
    issue to the library — notifying every single week for the same
    still-unowned release would be noise, not signal. So a Telegram/
    Discord notification (see kodex/delivery/notify.py's
    notify_new_release) only fires on an actual False→True transition,
    checked per series against the value before this run touched it.
    """
    db = SessionLocal()
    settings = get_settings()
    checked = 0
    with_new_release = 0
    newly_available = 0
    try:
        series_list = db.query(Series).filter(Series.is_following.is_(True)).all()
        for series in series_list:
            was_available = bool(series.new_release_available)
            try:
                if check_series_for_new_release(db, series, comicvine_api_key=settings.comicvine_api_key):
                    with_new_release += 1
                checked += 1
                db.commit()
                if not was_available and series.new_release_available:
                    newly_available += 1
                    notify_new_release(series, settings=settings)
            except Exception:
                logger.exception("Release check failed for series %s", series.id)
                db.rollback()

        logger.info(
            "Checked %d followed series for new releases, %d have something new (%d newly)",
            checked,
            with_new_release,
            newly_available,
        )
        return {
            "series_checked": checked,
            "series_with_new_release": with_new_release,
            "series_newly_available": newly_available,
        }
    finally:
        db.close()


def sorting_scan_task(intake_library_id: int) -> dict:
    """Classifies every top-level entry (folder, or occasionally a loose
    file) directly under one intake library's root that doesn't already
    have a SortingItem row — see kodex/acquire/sorting/classifier.py for how.
    High-confidence detections are immediately RESOLVED (ready for
    sorting_apply_task below); anything classifier.py wasn't sure about is
    left PENDING for the admin review queue (GET /sorting).

    Safe to re-run: existing source_paths (whatever their current status)
    are skipped, so this only ever adds proposals for genuinely new
    arrivals, never touches something already resolved/applied/skipped.
    """
    db = SessionLocal()
    try:
        library = db.get(Library, intake_library_id)
        if library is None:
            raise ValueError(f"Library {intake_library_id} not found")
        added = _classify_intake(db, library)
        return {"items_added": added}
    finally:
        db.close()


def _classify_intake(db, library: Library) -> int:
    """sorting_scan_task's body, shared with scan_library_task's automatic
    sorting. Returns how many new SortingItem rows were added."""
    settings = get_settings()
    root = settings.libraries_root / library.path
    if not root.is_dir():
        raise ValueError(f"Library path does not exist: {root}")

    existing_paths = {row[0] for row in db.query(SortingItem.source_path).all()}

    # Another library's own folder (or a folder containing one) can sit
    # directly under the intake when the intake's path is "." — never
    # classify it as a new arrival, or applying would move a whole
    # library. Same idea as the _sorterat guard below, for every library.
    other_library_roots = [
        (settings.libraries_root / other.path).resolve()
        for other in db.query(Library).filter(Library.id != library.id).all()
    ]

    added = 0
    for entry in sorted(root.iterdir()):
        if entry.name.startswith("."):
            continue
        resolved_entry = entry.resolve()
        if any(resolved_entry == other or resolved_entry in other.parents for other in other_library_roots):
            continue
        # _sorterat is the destination mount nested inside
        # libraries_root (see kodex/acquire/sorting/paths.py) — same reasoning as
        # the matching guard in scanner.py's scan_library: never treat
        # it as something to classify/move, that risks moving it into
        # one of its own subdirectories.
        if root == settings.libraries_root and entry.name == "_sorterat":
            continue
        source_path = str(entry.relative_to(root))
        if source_path in existing_paths:
            continue

        detected_type, reason = classify(entry)
        now = dt.datetime.utcnow() if detected_type else None
        db.add(
            SortingItem(
                source_path=source_path,
                detected_type=detected_type,
                detected_reason=reason,
                resolved_type=detected_type,
                status=SortingStatus.RESOLVED if detected_type else SortingStatus.PENDING,
                resolved_at=now,
            )
        )
        added += 1

    db.commit()
    logger.info("Sorting scan of library %s: %d new item(s) found", library.name, added)
    return added


def sorting_apply_task(intake_library_id: int) -> dict:
    """Physically moves every RESOLVED SortingItem out of the intake
    library and into its resolved_type's destination library (see
    kodex/acquire/sorting/paths.py for the fixed path convention those destination
    Library rows must already exist at), then enqueues a scan of every
    destination library that received at least one item so the moved
    books show up without an extra manual step.

    One item's move failing (most likely: a same-named folder already
    exists at the destination) doesn't stop the rest — the item stays
    RESOLVED with apply_error set, so it's retried on the next apply
    rather than silently lost.
    """
    db = SessionLocal()
    try:
        intake_library = db.get(Library, intake_library_id)
        if intake_library is None:
            raise ValueError(f"Library {intake_library_id} not found")
        return _apply_resolved_items(db, intake_library)
    finally:
        db.close()


def _apply_resolved_items(db, intake_library: Library) -> dict:
    """sorting_apply_task's body, shared with scan_library_task's automatic
    sorting."""
    settings = get_settings()
    intake_root = settings.libraries_root / intake_library.path

    destination_libraries: dict = {}
    for library_type, path in DESTINATION_LIBRARY_PATHS.items():
        library = db.query(Library).filter(Library.path == path).one_or_none()
        if library is None:
            raise ValueError(
                f"Destination library for {library_type.value} not found at path {path!r} "
                "— the sorting destination libraries need to be created first"
            )
        destination_libraries[library_type] = library

    items = db.query(SortingItem).filter(SortingItem.status == SortingStatus.RESOLVED).all()
    moved = 0
    failed = 0
    touched_library_ids: set[int] = set()

    for item in items:
        destination_library = destination_libraries[item.resolved_type]
        source_abs = intake_root / item.source_path
        destination_root = settings.libraries_root / destination_library.path

        if not source_abs.exists():
            item.apply_error = f"Källan finns inte längre: {source_abs}"
            failed += 1
            continue
        if destination_library.read_only or intake_library.read_only:
            item.apply_error = "Biblioteket är skrivskyddat"
            failed += 1
            continue

        try:
            shutil.move(str(source_abs), str(destination_root))
        except (shutil.Error, OSError) as exc:
            item.apply_error = str(exc)
            failed += 1
            continue

        item.status = SortingStatus.APPLIED
        item.applied_at = dt.datetime.utcnow()
        item.apply_error = None
        moved += 1
        touched_library_ids.add(destination_library.id)

    db.commit()

    scan_queue = get_scan_queue()
    for library_id in touched_library_ids:
        scan_queue.enqueue(scan_library_task, library_id, job_timeout="2h")

    logger.info("Sorting apply: moved %d item(s), %d failed", moved, failed)
    return {"moved": moved, "failed": failed, "libraries_rescanned": len(touched_library_ids)}


def write_comicinfo_task(intake_library_id: int) -> dict:
    """Writes/updates ComicInfo.xml inside every CBZ under each RESOLVED
    comics/manga SortingItem still sitting in the intake library (not yet
    moved by sorting_apply_task) — see kodex/acquire/sorting/comicinfo_writer.py.
    Series/Number/Year are best-effort parsed from the item's folder name;
    Manga is set from resolved_type, which is the whole point: once this
    file gets moved and (re)scanned, its embedded ComicInfo.xml carries
    that forward automatically (see kodex/acquire/sorting/classifier.py and
    scanner.py's own ComicInfo reading), instead of needing a separate
    metadata backfill step later. CBR files are skipped entirely — see
    comicinfo_writer.py's module docstring for why.

    One file's write failing (a corrupt/mislabeled archive) doesn't stop
    the rest — same "isolate failures per-item" pattern as
    enrich_library_task.
    """
    db = SessionLocal()
    try:
        library = db.get(Library, intake_library_id)
        if library is None:
            raise ValueError(f"Library {intake_library_id} not found")

        settings = get_settings()
        root = settings.libraries_root / library.path

        items = (
            db.query(SortingItem)
            .filter(
                SortingItem.status == SortingStatus.RESOLVED,
                SortingItem.resolved_type.in_([LibraryType.COMICS, LibraryType.MANGA]),
            )
            .all()
        )

        written = 0
        skipped_cbr = 0
        failed = 0

        for item in items:
            source_abs = root / item.source_path
            if not source_abs.exists():
                continue

            series, number, year = parse_series_and_number(Path(item.source_path).name)
            manga = "Yes" if item.resolved_type == LibraryType.MANGA else "No"

            targets = [source_abs] if source_abs.is_file() else sorted(source_abs.rglob("*"))
            for path in targets:
                if not path.is_file():
                    continue
                suffix = path.suffix.lower()
                if suffix == ".cbr":
                    skipped_cbr += 1
                    continue
                if suffix != ".cbz":
                    continue
                try:
                    write_comicinfo_to_cbz(path, series=series, number=number, year=year, manga=manga)
                    written += 1
                except Exception:
                    logger.exception("Writing ComicInfo.xml failed for %s", path)
                    failed += 1

        logger.info("ComicInfo write: %d file(s) written, %d cbr skipped, %d failed", written, skipped_cbr, failed)
        return {"written": written, "skipped_cbr": skipped_cbr, "failed": failed}
    finally:
        db.close()


def refresh_story_arc_task(story_arc_id: int) -> dict:
    """Fetches a StoryArc's full issue roster — from Metron if it's a
    Metron-sourced arc (metron_id set), from CBL-ReadingLists if it's a
    CBL-sourced one (cbl_path set), from League of Comic Geeks if it's
    that (locg_event_id set), from Comic Vine otherwise (see
    app/enrichment/story_arc_roster.py for Comic Vine, metron.py for
    Metron, cbl.py for CBL, leagueofcomicgeeks.py for LoCG) — and rebuilds
    its StoryArcIssue rows from scratch. A full replace rather than a
    diff/merge, since rosters are small (dozens, not thousands, of
    issues) and the source provider is
    the single source of truth here anyway. Each issue gets linked to an
    owned Book, if we have one, by matching comicvine_issue_id against
    BookMetadata.external_ids (all three roster sources report issues by
    Comic Vine issue id — see cbl.py/metron.py's own docstrings for why)
    — that link is what turns "in the roster" into "shown as owned" vs.
    "Saknas" in the frontend (Uppdrag 7 Del D).

    Also backfills BookMetadata.story_arcs (+ reindexes) for every owned
    match that doesn't already list this arc's name — necessary for a
    CBL-linked arc especially: CBL never touches a book's own metadata
    during matching (see cbl.py's docstring on why it can't — no reverse
    lookup), so without this, a CBL-linked collection would show 0 owned
    books despite StoryArcIssue.book_id correctly linking them, since the
    collection itself is a SMART one filtered by story_arcs (see
    engine.py's _ensure_arc_collections). Harmless and idempotent for
    Comic Vine/Metron-sourced arcs too, where this is normally already
    set from the original match — a cheap self-heal if it ever drifted.
    """
    db = SessionLocal()
    try:
        story_arc = db.get(StoryArc, story_arc_id)
        if story_arc is None:
            raise ValueError(f"StoryArc {story_arc_id} not found")

        settings = get_settings()
        if story_arc.metron_id is not None:
            if not settings.metron_username or not settings.metron_password:
                raise ValueError("METRON_USERNAME/METRON_PASSWORD are not configured")
            roster = metron.fetch_arc_roster(story_arc.metron_id, settings.metron_username, settings.metron_password)
        elif story_arc.cbl_path is not None:
            roster = cbl.fetch_reading_list(story_arc.cbl_path)
        elif story_arc.locg_event_id is not None:
            roster = leagueofcomicgeeks.fetch_event_roster(story_arc.locg_event_id)
        else:
            if not settings.comicvine_api_key:
                raise ValueError("COMICVINE_API_KEY is not configured")
            roster = fetch_arc_roster(story_arc.comicvine_id, settings.comicvine_api_key)

        # Full replace: simpler and just as correct as a diff for a list
        # this size, and guarantees order_index always matches roster
        # order exactly rather than accumulating drift across re-fetches.
        db.query(StoryArcIssue).filter(StoryArcIssue.story_arc_id == story_arc.id).delete()

        issue_ids = [item.comicvine_issue_id for item in roster]
        owned_book_by_issue_id: dict[int, int] = {}
        if issue_ids:
            rows = (
                db.query(BookMetadata)
                .join(Book, Book.id == BookMetadata.book_id)
                .filter(BookMetadata.external_ids["comicvine_issue_id"].as_integer().in_(issue_ids))
                .all()
            )
            for meta in rows:
                issue_id = (meta.external_ids or {}).get("comicvine_issue_id")
                if issue_id is None:
                    continue
                owned_book_by_issue_id[int(issue_id)] = meta.book_id
                current_arcs = meta.story_arcs or []
                if story_arc.name not in current_arcs:
                    meta.story_arcs = [*current_arcs, story_arc.name]
                    db.add(meta)

        for index, item in enumerate(roster):
            db.add(
                StoryArcIssue(
                    story_arc_id=story_arc.id,
                    comicvine_issue_id=item.comicvine_issue_id,
                    order_index=index,
                    display_name=item.display_name,
                    cover_url=item.cover_url,
                    site_detail_url=item.site_detail_url,
                    book_id=owned_book_by_issue_id.get(item.comicvine_issue_id),
                )
            )

        story_arc.roster_fetched_at = dt.datetime.now(dt.UTC)
        db.add(story_arc)
        db.commit()

        owned_count = len(owned_book_by_issue_id)
        logger.info(
            "Refreshed story arc %s (%s): %d issues, %d owned, %d missing",
            story_arc.id,
            story_arc.name,
            len(roster),
            owned_count,
            len(roster) - owned_count,
        )
        return {"issue_count": len(roster), "owned_count": owned_count, "missing_count": len(roster) - owned_count}
    finally:
        db.close()


def start_download_task(download_id: int, source_url: str) -> dict:
    """Batch C (C10) — hands `source_url` (a magnet link for QBITTORRENT,
    an .nzb URL for SABNZBD) to the configured download client and
    records the client's own tracking id (torrent hash / nzo_id) on the
    Download row. `source_url` is a job argument, not a Download column —
    nothing else ever needs to re-read it once the client has accepted it.

    DIRECT_HTTP downloads (Anna's Archive/GetComics — a plain file URL,
    no torrent/nzb protocol) never reach this task at all; the route that
    creates them fetches the file itself and marks the Download COMPLETED
    (or NEEDS_REVIEW for a gated Anna's Archive link) synchronously,
    since there's no separate client to poll afterwards.
    """
    db = SessionLocal()
    try:
        download = db.get(Download, download_id)
        if download is None:
            raise ValueError(f"Download {download_id} not found")

        settings = get_settings()
        try:
            if download.client == DownloadClientType.QBITTORRENT:
                qbt = QBittorrentClient(
                    settings.qbittorrent_url, settings.qbittorrent_username, settings.qbittorrent_password
                )
                try:
                    external_id = qbt.add_magnet(source_url, save_path=str(settings.downloads_staging_dir))
                finally:
                    qbt.close()
            elif download.client == DownloadClientType.SABNZBD:
                sab = SabnzbdClient(settings.sabnzbd_url, settings.sabnzbd_api_key)
                try:
                    external_id = sab.add_url(source_url)
                finally:
                    sab.close()
            else:
                raise DownloadClientError(f"start_download_task doesn't handle client={download.client}")
        except DownloadClientError as exc:
            logger.exception("Failed to start download %s", download_id)
            download.status = DownloadStatus.FAILED
            download.error_message = str(exc)
            db.add(download)
            db.commit()
            return {"status": "failed", "error": str(exc)}

        download.external_id = external_id
        download.status = DownloadStatus.DOWNLOADING
        db.add(download)
        db.commit()
        return {"status": "downloading", "external_id": external_id}
    finally:
        db.close()


_UNSAFE_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*]')


def fetch_direct_http_download_task(download_id: int, source_url: str) -> dict:
    """Batch C (C12) — DIRECT_HTTP downloads (GetComics via FlareSolverr;
    Anna's Archive stays interactive-only and never reaches this task,
    see C13) have no separate download client to hand a link to and poll
    afterwards — this job fetches the file itself, synchronously, inside
    the one job. Once the file is on disk it hands straight off to
    import_completed_download_task (called directly, not re-enqueued —
    same worker process, no reason to round-trip through the queue) for
    the same move-into-library step every other completed download goes
    through.
    """
    db = SessionLocal()
    try:
        download = db.get(Download, download_id)
        if download is None:
            raise ValueError(f"Download {download_id} not found")

        settings = get_settings()
        target_dir = settings.downloads_staging_dir / f"direct-{download_id}"
        suffix = Path(httpx.URL(source_url).path).suffix or ".bin"
        safe_title = _UNSAFE_FILENAME_CHARS_RE.sub("_", download.title).strip() or f"download-{download_id}"
        target_path = target_dir / f"{safe_title}{suffix}"

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            with httpx.stream("GET", source_url, timeout=300.0, follow_redirects=True) as response:
                response.raise_for_status()
                with target_path.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
        except httpx.HTTPError as exc:
            logger.exception("Failed to fetch direct-http download %s", download_id)
            download.status = DownloadStatus.FAILED
            download.error_message = str(exc)
            db.add(download)
            db.commit()
            return {"status": "failed", "error": str(exc)}

        download.save_path = str(target_dir)
        db.add(download)
        db.commit()
    finally:
        db.close()

    return import_completed_download_task(download_id)


def import_completed_download_task(download_id: int) -> dict:
    """Batch C (C10) — moves a finished download's files (see
    Download.save_path, already path-mapped via DOWNLOAD_PATH_MAP_TORRENT/
    USENET — see kodex/acquire/clients/manager.py's map_download_path) into
    Download.library_id's folder, then triggers the same rescan trigger_
    scan/upload_book_file (B7) already use. Only files with an
    IMPORTABLE_EXTENSIONS suffix are moved — a download often includes
    .nfo/.txt/sample files alongside the real comic/book, none of which
    belong in a library folder. Fulfills the linked Request, if any (see
    the Batch-C Request tie-in), same terminal status a manually-fulfilled
    request gets.
    """
    db = SessionLocal()
    try:
        download = db.get(Download, download_id)
        if download is None:
            raise ValueError(f"Download {download_id} not found")

        if download.library_id is None or not download.save_path:
            download.status = DownloadStatus.FAILED
            download.error_message = "No target library or save_path set — cannot import"
            db.add(download)
            db.commit()
            return {"status": "failed", "error": download.error_message}

        library = db.get(Library, download.library_id)
        if library is None:
            download.status = DownloadStatus.FAILED
            download.error_message = f"Library {download.library_id} no longer exists"
            db.add(download)
            db.commit()
            return {"status": "failed", "error": download.error_message}

        settings = get_settings()
        # DIRECT_HTTP downloads (C12) are fetched straight onto this same
        # worker's own filesystem by fetch_direct_http_download_task — no
        # separate download-client host is involved, so no path
        # translation applies (unlike QBITTORRENT/SABNZBD, which may run
        # on a different host than this worker — see DOWNLOAD_PATH_MAP_*'s
        # own docstring in config.py).
        if download.client == DownloadClientType.QBITTORRENT:
            mapping = settings.download_path_map_torrent
        elif download.client == DownloadClientType.SABNZBD:
            mapping = settings.download_path_map_usenet
        else:
            mapping = ""
        source_path = Path(map_download_path(download.save_path, mapping))
        library_root = settings.libraries_root / library.path

        if source_path.is_file():
            candidates = [source_path] if source_path.suffix.lower() in IMPORTABLE_EXTENSIONS else []
        elif source_path.is_dir():
            candidates = [
                p for p in source_path.rglob("*") if p.is_file() and p.suffix.lower() in IMPORTABLE_EXTENSIONS
            ]
        else:
            candidates = []

        if not candidates:
            download.status = DownloadStatus.FAILED
            download.error_message = (
                f"No importable files (of {sorted(IMPORTABLE_EXTENSIONS)}) found under {source_path}"
            )
            db.add(download)
            db.commit()
            return {"status": "failed", "error": download.error_message}

        library_root.mkdir(parents=True, exist_ok=True)
        moved = 0
        for candidate in candidates:
            target = library_root / candidate.name
            if target.exists():
                logger.warning("Skipping %s — already exists at %s", candidate, target)
                continue
            shutil.move(str(candidate), str(target))
            moved += 1

        get_scan_queue().enqueue(scan_library_task, library.id, job_timeout="2h")

        download.status = DownloadStatus.COMPLETED
        db.add(download)

        if download.request_id is not None:
            request = db.get(Request, download.request_id)
            if request is not None:
                request.status = RequestStatus.FULFILLED
                db.add(request)

        db.commit()
        return {"status": "completed", "files_moved": moved}
    finally:
        db.close()


def write_back_library_task(library_id: int) -> dict:
    """ComicInfo.xml into the library's CBZ files and series.json into its
    series folders (kodex.library.write_back); only in a library with
    write-back on."""
    from kodex.library.write_back import write_back_library

    db = SessionLocal()
    try:
        library = db.get(Library, library_id)
        if library is None:
            raise ValueError(f"Library {library_id} not found")
        return write_back_library(db, library, get_settings().libraries_root)
    finally:
        db.close()


def convert_book_task(book_id: int) -> dict:
    """Converts a CBR or CB7 to CBZ next to it (kodex.library.write_back);
    the original stays until someone deletes it."""
    from kodex.library.write_back import convert_to_cbz

    db = SessionLocal()
    try:
        book = db.get(Book, book_id)
        if book is None:
            raise ValueError(f"Book {book_id} not found")
        target = convert_to_cbz(db, book, get_settings().libraries_root)
        db.commit()
        return {"converted_to": target.name}
    finally:
        db.close()
