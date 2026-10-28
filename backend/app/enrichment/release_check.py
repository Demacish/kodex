"""Weekly "does this followed series have a new release?" check — see
"Modul: Följda serier" in arkitekturplanen.

Deliberately reuses the external ids already stored on the series' books
from earlier enrichment (BookMetadata.external_ids) rather than doing a
fresh title search: a series only starts getting checked once at least
one of its books has already been matched to Comic Vine/AniList through
the normal enrichment flow (automatic or manual). No new matching step,
no new UI for picking a series-level external id — this only ever reads
ids that already exist.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import Counter

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.enrichment import anilist, comicvine
from app.enrichment.http import get_client
from app.models.book import Book
from app.models.enums import LibraryType
from app.models.metadata import BookMetadata
from app.models.release_event import SeriesReleaseEvent
from app.models.series import Series

logger = logging.getLogger(__name__)


def _parse_comicvine_date(raw: str | None) -> dt.date | None:
    """Comic Vine's date fields come back as e.g. "2025-06-15 00:00:00" —
    lenient on anything else so a format change/empty string degrades to
    "no date" rather than crashing the whole sync.
    """
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _owned_comicvine_issue_ids(db: Session, series_id: int) -> dict[str, int]:
    """external comicvine_issue_id -> Book.id, for every book in this
    series already matched down to a specific issue — B5's "owned" status
    for a release event (see _sync_release_events below).
    """
    rows = (
        db.query(Book.id, BookMetadata.external_ids)
        .join(BookMetadata, BookMetadata.book_id == Book.id)
        .filter(Book.series_id == series_id)
        .all()
    )
    owned: dict[str, int] = {}
    for book_id, external_ids in rows:
        issue_id = (external_ids or {}).get("comicvine_issue_id")
        if issue_id is not None:
            owned[str(issue_id)] = book_id
    return owned


def _sync_release_events(db: Session, series: Series, volume_id: str, comicvine_api_key: str, client) -> None:
    """B5 — upserts one SeriesReleaseEvent per issue Comic Vine lists for
    this volume, keyed on external_issue_id so a re-run updates
    (store_date can move) rather than duplicates. Best-effort: an issue
    list failure here (comicvine.list_issue_releases already logs and
    returns []) just means the calendar doesn't gain new entries this
    week — it must never break the plain count-based new_release_available
    check this function is called alongside.
    """
    releases = comicvine.list_issue_releases(volume_id, comicvine_api_key, client=client)
    if not releases:
        return

    existing_by_external_id = {
        event.external_issue_id: event
        for event in db.query(SeriesReleaseEvent).filter(SeriesReleaseEvent.series_id == series.id).all()
    }
    owned_by_external_id = _owned_comicvine_issue_ids(db, series.id)

    for release in releases:
        event = existing_by_external_id.get(release.external_id)
        if event is None:
            event = SeriesReleaseEvent(series_id=series.id, external_issue_id=release.external_id, provider="comicvine")
        event.issue_number = release.issue_number
        event.title = release.title
        event.store_date = _parse_comicvine_date(release.store_date)
        event.cover_date = _parse_comicvine_date(release.cover_date)
        event.owned_book_id = owned_by_external_id.get(release.external_id)
        db.add(event)


def _most_common_external_id(db: Session, series_id: int, key: str) -> str | None:
    """Most of a series' books should share the same volume/AniList id once
    enriched, but not necessarily all of them (a stray mismatched issue, a
    manual correction on just one book) — take the most common value
    rather than just the first row, so one outlier doesn't send every
    future check to the wrong external series.
    """
    rows = (
        db.query(BookMetadata.external_ids)
        .join(Book, Book.id == BookMetadata.book_id)
        .filter(Book.series_id == series_id)
        .all()
    )
    values = [str(row[0][key]) for row in rows if row[0] and row[0].get(key) is not None]
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def _owned_count(db: Session, series_id: int) -> int:
    """How many issues/volumes of this series the library already has —
    the number this check compares an external published-count against.
    Uses whichever is higher of the highest `Book.number` seen and the
    plain row count, so a library missing an early issue (row count too
    low) or a book with no parsed number at all (falls back to the count)
    doesn't produce a false "new release" purely from that gap.
    """
    max_number = db.query(func.max(Book.number)).filter(Book.series_id == series_id).scalar()
    count = db.query(func.count(Book.id)).filter(Book.series_id == series_id).scalar() or 0
    if max_number is not None:
        return max(int(max_number), count)
    return count


def check_series_for_new_release(db: Session, series: Series, *, comicvine_api_key: str) -> bool:
    """Best-effort — returns whether `series.new_release_available` is
    True after this check, whether that's freshly detected here or just
    the state carried over unchanged.

    Leaves `known_release_count`/`new_release_available` exactly as they
    were (but still stamps `last_release_check_at`) when no external id
    can be found yet, or the provider can't say — that's a real
    "can't tell", never treated as "nothing new" or "no releases".
    """
    library_type = series.library.library_type
    owned = _owned_count(db, series.id)
    client = get_client()
    published: int | None = None
    try:
        if library_type == LibraryType.COMICS:
            volume_id = _most_common_external_id(db, series.id, "comicvine_volume_id")
            if volume_id is not None and comicvine_api_key:
                published = comicvine.fetch_issue_count(volume_id, comicvine_api_key, client=client)
                # B5 — the per-issue release calendar's data source. Runs
                # alongside the plain count check above rather than
                # replacing it: new_release_available's count comparison
                # is unaffected either way, this only ever adds/updates
                # SeriesReleaseEvent rows.
                _sync_release_events(db, series, volume_id, comicvine_api_key, client)
        elif library_type == LibraryType.MANGA:
            anilist_id = _most_common_external_id(db, series.id, "anilist_id")
            if anilist_id is not None:
                published = anilist.fetch_release_count(anilist_id, client=client)
        # EBOOKS/MIXED: neither Open Library nor Google Books exposes a
        # "how many books are in this series" count, and ebook series in
        # the wild are rarely modeled with one anywhere reliable — nothing
        # to check against, so published stays None for those.
    finally:
        client.close()

    series.last_release_check_at = dt.datetime.now(dt.UTC)
    if published is not None:
        series.known_release_count = published
        series.new_release_available = published > owned
    db.add(series)
    return bool(series.new_release_available)
