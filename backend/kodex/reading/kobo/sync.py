"""The library a Kobo e-reader syncs, in the Kobo store's terms: book
entitlements and metadata, reading states, and the sync token that says
how far the device has come.

A book is a Kobo "entitlement" with a UUID made from its id. The device
gets the EPUBs of its collection; a book that leaves the collection is
sent as removed. Positions the user reached elsewhere (the web reader,
KOReader, an OPDS app) are sent as reading states with their progression;
the device's own come back as kind ``kobo`` locators."""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.book import Book
from app.models.collection import Collection
from app.models.enums import BookFormat
from app.models.reading_progress import ReadingProgress
from kodex.collections import members
from kodex.reading.models import KoboBook, KoboDevice

PAGE = 100  # entitlements per sync answer; the device asks again for the rest
_UUID_PREFIX = "6b6f6465-7800-4000-8000-"  # "kodex" in hex, then a version 4 / variant 1 layout
_SERIES_PREFIX = "6b6f6465-7801-4000-8000-"
CATEGORY = "00000000-0000-0000-0000-000000000001"


def book_uuid(book_id: int) -> str:
    return f"{_UUID_PREFIX}{book_id:012x}"


def book_id_of(value: str) -> int | None:
    if not value.startswith(_UUID_PREFIX):
        return None
    try:
        return int(value[len(_UUID_PREFIX) :], 16)
    except ValueError:
        return None


def stamp(value: dt.datetime | None) -> str:
    value = value or dt.datetime.now(dt.UTC)
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Token:
    """x-kobo-synctoken: how far this server's sync came, and the store's
    own token when the store's library is synced too."""

    states_since: dt.datetime | None = None
    store: str | None = None
    fresh: bool = True  # no token of ours: the device starts over

    @classmethod
    def parse(cls, header: str | None) -> Token:
        if not header:
            return cls()
        try:
            data = json.loads(base64.b64decode(header + "=" * (-len(header) % 4)))
        except ValueError, binascii.Error, UnicodeDecodeError:
            return cls(store=header)  # the store's own, from before this server
        if not isinstance(data, dict) or "kodex" not in data:
            return cls(store=header)
        ours = data.get("kodex") or {}
        since = ours.get("states_since")
        return cls(states_since=dt.datetime.fromisoformat(since) if since else None, store=data.get("store"),
                   fresh=False)  # fmt: skip

    def header(self) -> str:
        data = {"kodex": {"states_since": self.states_since.isoformat() if self.states_since else None},
                "store": self.store}  # fmt: skip
        return base64.b64encode(json.dumps(data).encode()).decode()


def metadata(book: Book, download_url: str, download_format: str, size: int) -> dict[str, Any]:
    uuid = book_uuid(book.id)
    meta = book.book_metadata
    authors = (meta.authors if meta else None) or []
    data: dict[str, Any] = {
        "Categories": [CATEGORY],
        "CoverImageId": uuid,
        "CrossRevisionId": uuid,
        "CurrentDisplayPrice": {"CurrencyCode": "USD", "TotalAmount": 0},
        "CurrentLoveDisplayPrice": {"TotalAmount": 0},
        "Description": (meta.summary if meta else None) or "",
        "DownloadUrls": [{"Format": download_format, "Size": size, "Url": download_url, "Platform": "Generic"}],
        "EntitlementId": uuid,
        "ExternalIds": [],
        "Genre": CATEGORY,
        "IsEligibleForKoboLove": False,
        "IsInternetArchive": False,
        "IsPreOrder": False,
        "IsSocialEnabled": True,
        "Language": (meta.language if meta else None) or "en",
        "PhoneticPronunciations": {},
        "PublicationDate": stamp(dt.datetime(meta.published_year, 1, 1, tzinfo=dt.UTC))
        if meta and meta.published_year
        else stamp(book.added_at),
        "Publisher": {"Imprint": "", "Name": (meta.publisher if meta else None) or ""},
        "RevisionId": uuid,
        "Title": (meta.title if meta and meta.title else book.file_path.rsplit("/", 1)[-1]),
        "WorkId": uuid,
        "ContributorRoles": [{"Name": name} for name in authors],
        "Contributors": authors,
    }
    if book.series is not None:
        data["Series"] = {"Name": book.series.title, "Number": f"{book.number:g}" if book.number is not None else "",
                          "NumberFloat": book.number or 0.0, "Id": f"{_SERIES_PREFIX}{book.series.id:012x}"}  # fmt: skip
    return data


def entitlement(book: Book, *, removed: bool = False) -> dict[str, Any]:
    uuid = book_uuid(book.id)
    return {
        "Accessibility": "Full",
        "ActivePeriod": {"From": stamp(book.added_at)},
        "Created": stamp(book.added_at),
        "CrossRevisionId": uuid,
        "Id": uuid,
        "IsHiddenFromArchive": False,
        "IsLocked": False,
        "IsRemoved": removed,
        "LastModified": stamp(book.updated_at),
        "OriginCategory": "Imported",
        "RevisionId": uuid,
        "Status": "Active",
    }


def reading_state(book: Book, progress: ReadingProgress | None) -> dict[str, Any]:
    uuid = book_uuid(book.id)
    modified = stamp(progress.last_read_at if progress else book.added_at)
    percent = progress.progress_percent if progress else 0.0
    if progress is not None and progress.is_finished:
        status = "Finished"
    elif percent > 0:
        status = "Reading"
    else:
        status = "ReadyToRead"
    bookmark: dict[str, Any] = {"LastModified": modified}
    if progress is not None and percent > 0:
        bookmark["ProgressPercent"] = round(percent, 2)
        if progress.locator_kind == "kobo" and progress.position:
            location = json.loads(progress.position)
            bookmark["Location"] = {"Value": location.get("value"), "Type": location.get("type") or "KoboSpan",
                                    "Source": location.get("source")}  # fmt: skip
            if location.get("chapter_percent") is not None:
                bookmark["ContentSourceProgressPercent"] = location["chapter_percent"]
    return {
        "EntitlementId": uuid,
        "Created": modified,
        "LastModified": modified,
        "PriorityTimestamp": modified,
        "StatusInfo": {"LastModified": modified, "Status": status, "TimesStartedReading": 1 if percent > 0 else 0},
        "Statistics": {"LastModified": modified},
        "CurrentBookmark": bookmark,
    }


def location(bookmark: dict[str, Any]) -> str | None:
    """A Kobo bookmark's location as a ``kobo`` locator."""
    found = bookmark.get("Location") or {}
    if not isinstance(found, dict) or not found.get("Value"):
        return None
    value = {"value": str(found["Value"])[:100], "source": str(found.get("Source") or "")[:300],
             "type": str(found.get("Type") or "KoboSpan")[:20],
             "chapter_percent": bookmark.get("ContentSourceProgressPercent")}  # fmt: skip
    return json.dumps(value, separators=(",", ":"))[:512]


def wanted(db: Session, device: KoboDevice) -> list[Book]:
    """The EPUBs of the device's collection."""
    if device.collection_id is None:
        return []
    collection = db.get(Collection, device.collection_id)
    if collection is None:
        return []
    ids = members.book_ids(db, collection)
    if not ids:
        return []
    query = (select(Book).where(Book.id.in_(ids), Book.file_format == BookFormat.EPUB)
             .options(selectinload(Book.book_metadata), selectinload(Book.series)).order_by(Book.id))  # fmt: skip
    return list(db.scalars(query))


@dataclass
class Changes:
    items: list[dict[str, Any]]
    more: bool


def changes(db: Session, device: KoboDevice, user_id: int, token: Token, device_id: str,
            describe: Any) -> Changes:  # fmt: skip
    """What the device hasn't got: new and changed books, removed ones,
    and reading states from elsewhere. ``describe(book)`` is the book's
    metadata. Updates what the device is known to have; the caller
    commits."""
    now = dt.datetime.now(dt.UTC)
    if token.fresh:
        db.query(KoboBook).filter(KoboBook.device_id == device.id).delete()
    known = {kb.book_id: kb for kb in db.scalars(select(KoboBook).where(KoboBook.device_id == device.id))}
    books = wanted(db, device)
    ids = {book.id for book in books}
    progress = {p.book_id: p for p in db.scalars(select(ReadingProgress).where(
        ReadingProgress.user_id == user_id, ReadingProgress.book_id.in_(ids | set(known))))}  # fmt: skip
    items: list[dict[str, Any]] = []
    sent: set[int] = set()
    for book in books:
        kb = known.get(book.id)
        if kb is not None and not kb.removed and book.updated_at <= kb.synced_at:
            continue
        if len(items) >= PAGE:
            return Changes(items, more=True)
        key = "NewEntitlement" if kb is None or kb.removed else "ChangedEntitlement"
        items.append({key: {"BookEntitlement": entitlement(book), "BookMetadata": describe(book),
                            "ReadingState": reading_state(book, progress.get(book.id))}})  # fmt: skip
        sent.add(book.id)
        if kb is None:
            db.add(KoboBook(device_id=device.id, book_id=book.id, synced_at=now, removed=False))
        else:
            kb.synced_at, kb.removed = now, False
    gone = [kb for kb in known.values() if kb.book_id not in ids and not kb.removed]
    for kb in gone:
        leaving = db.get(Book, kb.book_id)
        if leaving is not None:
            items.append({"ChangedEntitlement": {"BookEntitlement": entitlement(leaving, removed=True),
                                                 "BookMetadata": describe(leaving)}})  # fmt: skip
        kb.removed = True
    for book in books:
        found = progress.get(book.id)
        if book.id in sent or found is None or found.device_id == device_id:
            continue
        if token.states_since is None or found.last_read_at > token.states_since:
            items.append({"ChangedReadingState": {"ReadingState": reading_state(book, found)}})
    token.states_since = now
    token.fresh = False
    device.last_sync_at = now
    return Changes(items, more=False)
