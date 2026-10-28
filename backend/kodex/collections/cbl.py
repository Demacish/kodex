"""Reading lists as CBL files (the ComicRack format Kavita, Komga, Mylar
and CBL-ReadingLists use): a collection out, in its order, with Comic Vine
ids where they are known; and a file in, as a manual collection of the
books here that it lists, with the ones that are missing.

A listed book is found by its Comic Vine issue id, or else by its series
and number (and the series' year when two series share a name)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.book import Book
from app.models.collection import Collection, collection_books
from app.models.enums import CollectionType
from app.models.metadata import BookMetadata
from app.models.series import Series
from kodex.collections import members

MAX_BYTES = 5_000_000


class CblError(ValueError):
    """The file isn't a reading list."""


@dataclass(frozen=True)
class Entry:
    series: str
    number: str | None
    volume: str | None
    year: str | None
    comicvine_issue: int | None


@dataclass(frozen=True)
class Imported:
    collection: Collection
    matched: int
    missing: list[Entry]


def _number(book: Book) -> str:
    if book.number_label:
        return book.number_label
    if book.number is None:
        return ""
    return f"{book.number:g}"


def export(db: Session, collection: Collection, user_id: int) -> bytes:
    ids = members.book_ids(db, collection, user_id)
    found = {b.id: b for b in db.scalars(select(Book).where(Book.id.in_(ids))
                                          .options(selectinload(Book.book_metadata), selectinload(Book.series)))}  # fmt: skip
    root = ET.Element("ReadingList", {"xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
                                      "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance"})  # fmt: skip
    ET.SubElement(root, "Name").text = collection.name
    ET.SubElement(root, "NumIssues").text = str(len(ids))
    books = ET.SubElement(root, "Books")
    for book_id in ids:
        book = found.get(book_id)
        if book is None:
            continue
        meta = book.book_metadata
        series = book.series.title if book.series else (meta.title if meta else book.file_path)
        attrs = {"Series": series, "Number": _number(book)}
        if book.series is not None and book.series.start_year:
            attrs["Volume"] = str(book.series.start_year)
        if meta is not None and meta.published_year:
            attrs["Year"] = str(meta.published_year)
        entry = ET.SubElement(books, "Book", attrs)
        external = (meta.external_ids if meta else None) or {}
        if external.get("comicvine_issue_id"):
            database = {"Name": "cv", "Issue": str(external["comicvine_issue_id"])}
            if external.get("comicvine_volume_id"):
                database["Series"] = str(external["comicvine_volume_id"])
            ET.SubElement(entry, "Database", database)
    ET.indent(root)
    data: bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return data


def parse(data: bytes) -> tuple[str | None, list[Entry]]:
    if len(data) > MAX_BYTES:
        raise CblError("The file is too big for a reading list")
    if b"<!DOCTYPE" in data[:2000] or b"<!ENTITY" in data:
        raise CblError("A reading list has no DOCTYPE")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise CblError(f"Not a reading list: {exc}") from exc
    if root.tag != "ReadingList":
        raise CblError("Not a reading list (no <ReadingList>)")
    entries = []
    for book in root.iter("Book"):
        issue = None
        for database in book.findall("Database"):
            if database.get("Name") == "cv" and (database.get("Issue") or "").isdigit():
                issue = int(database.get("Issue") or 0)
        entries.append(Entry(series=(book.get("Series") or "").strip(), number=book.get("Number"),
                             volume=book.get("Volume"), year=book.get("Year"), comicvine_issue=issue))  # fmt: skip
    return (root.findtext("Name") or None), entries


def _key(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return re.sub(r"[^\w]+", " ", "".join(c for c in folded if not unicodedata.combining(c))).strip()


def _number_key(value: str | None) -> str:
    value = (value or "").strip().lstrip("#").lstrip("0") or "0"
    try:
        return f"{float(value):g}"
    except ValueError:
        return value.casefold()


def import_(db: Session, data: bytes, owner_user_id: int | None = None, name: str | None = None) -> Imported:
    """A manual collection of the listed books here, in the list's order."""
    title, entries = parse(data)
    by_issue: dict[int, int] = {}
    issues = [e.comicvine_issue for e in entries if e.comicvine_issue]
    if issues:
        rows = db.execute(select(BookMetadata.book_id, BookMetadata.external_ids["comicvine_issue_id"].as_integer())
                          .where(BookMetadata.external_ids["comicvine_issue_id"].as_integer().in_(issues))).all()  # fmt: skip
        by_issue = {int(issue): int(book_id) for book_id, issue in rows}
    wanted_series = {_key(e.series) for e in entries if e.series}
    series_rows = [s for s in db.scalars(select(Series)) if _key(s.title) in wanted_series]
    books_of: dict[tuple[str, str], list[tuple[Series, Book]]] = {}
    if series_rows:
        for book in db.scalars(select(Book).where(Book.series_id.in_([s.id for s in series_rows]),
                                                  Book.missing_since.is_(None))):  # fmt: skip
            series = next(s for s in series_rows if s.id == book.series_id)
            books_of.setdefault((_key(series.title), _number_key(_number(book))), []).append((series, book))
    chosen: list[int] = []
    missing: list[Entry] = []
    for entry in entries:
        book_id = by_issue.get(entry.comicvine_issue or -1)
        if book_id is None:
            candidates = books_of.get((_key(entry.series), _number_key(entry.number)), [])
            if len(candidates) > 1 and (entry.volume or entry.year):
                year = entry.volume or entry.year
                candidates = [c for c in candidates if str(c[0].start_year or "") == year] or candidates
            book_id = candidates[0][1].id if candidates else None
        if book_id is None or book_id in chosen:
            if book_id is None:
                missing.append(entry)
            continue
        chosen.append(book_id)
    collection = Collection(name=(name or title or "Läslista")[:255], collection_type=CollectionType.MANUAL,
                            owner_user_id=owner_user_id)  # fmt: skip
    db.add(collection)
    db.flush()
    for position, book_id in enumerate(chosen):
        db.execute(collection_books.insert().values(collection_id=collection.id, book_id=book_id, position=position))
    return Imported(collection, len(chosen), missing)
