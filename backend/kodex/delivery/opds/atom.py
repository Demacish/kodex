"""OPDS 1.2 (Atom) with Page Streaming 1.2, for KOReader, Panels, Chunky,
Moon+ Reader and the like.

    /opds/                         the start: reading now, newest, followed, libraries
    /opds/reading, /opds/latest    acquisition feeds
    /opds/followed                 followed series
    /opds/libraries/{id}           a library's series (and loose books)
    /opds/series/{id}              a series' books
    /opds/search?q=                books by title, series or author
    /opds/search-description.xml   OpenSearch
    /opds/books/{id}/file          the file
    /opds/books/{id}/cover         the cover as JPEG (?size=small|medium|large)
    /opds/books/{id}/pages/{n}     page n (0-based) as JPEG, ?width= narrows it (PSE)

Feeds come in pages of catalog.PAGE_SIZE with first/previous/next/last
links. A comic's entry has a PSE stream link with the page count and the
last page read, 0-based."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal
from urllib.parse import quote, urlencode
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.auth import get_current_user_via_opds_token
from app.config import get_settings
from app.database import get_db
from app.models.book import Book
from app.models.enums import PAGE_BASED_FORMATS, BookFormat
from app.models.reading_progress import ReadingProgress
from app.models.series import Series
from app.models.user import User
from kodex.delivery.opds import catalog, files, reports

router = APIRouter(prefix="/opds", tags=["opds"])

ATOM = "http://www.w3.org/2005/Atom"
NAMESPACES = {
    "": ATOM,
    "dc": "http://purl.org/dc/terms/",
    "opds": "http://opds-spec.org/2010/catalog",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    "pse": "http://vaemendis.net/opds-pse/ns",
}
for _prefix, _uri in NAMESPACES.items():
    ET.register_namespace(_prefix, _uri)

NAVIGATION = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQUISITION = "application/atom+xml;profile=opds-catalog;kind=acquisition"
PSE_STREAM = "http://vaemendis.net/opds-pse/stream"
MIME_TYPES = {
    BookFormat.EPUB: "application/epub+zip",
    BookFormat.PDF: "application/pdf",
    BookFormat.CBZ: "application/vnd.comicbook+zip",
    BookFormat.CBR: "application/vnd.comicbook-rar",
    BookFormat.CB7: "application/x-cb7",
}


def _q(namespace: str, name: str) -> str:
    return f"{{{NAMESPACES[namespace]}}}{name}"


def _stamp(value: dt.datetime | None) -> str:
    value = value or dt.datetime.now(dt.UTC)
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _link(parent: ET.Element, rel: str, href: str, type_: str, **attrs: str) -> ET.Element:
    return ET.SubElement(parent, _q("", "link"), {"rel": rel, "href": href, "type": type_, **attrs})


def _text(parent: ET.Element, tag: str, value: str, namespace: str = "", **attrs: str) -> ET.Element:
    element = ET.SubElement(parent, _q(namespace, tag), attrs)
    element.text = value
    return element


def _href(path: str, **params: object) -> str:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    return f"{path}?{query}" if query else path


class Feed:
    def __init__(self, feed_id: str, title: str, path: str, kind: str, page: catalog.Page[Any] | None = None,
                 **params: object) -> None:  # fmt: skip
        self.root = ET.Element(_q("", "feed"))
        self.kind = kind
        _text(self.root, "id", feed_id)
        _text(self.root, "title", title)
        _text(self.root, "updated", _stamp(None))
        author = ET.SubElement(self.root, _q("", "author"))
        _text(author, "name", "Kodex")
        number = page.number if page is not None else 1
        _link(self.root, "self", _href(path, **params, page=number if number > 1 else None), kind)
        _link(self.root, "start", "/opds/", NAVIGATION)
        _link(self.root, "search", "/opds/search-description.xml", "application/opensearchdescription+xml")
        if page is not None and page.last > 1:
            _text(self.root, "totalResults", str(page.total), "opensearch")
            _text(self.root, "itemsPerPage", str(page.size), "opensearch")
            _text(self.root, "startIndex", str((page.number - 1) * page.size + 1), "opensearch")
            _link(self.root, "first", _href(path, **params), kind)
            _link(self.root, "last", _href(path, **params, page=page.last), kind)
            if page.number > 1:
                _link(self.root, "previous", _href(path, **params, page=page.number - 1), kind)
            if page.number < page.last:
                _link(self.root, "next", _href(path, **params, page=page.number + 1), kind)

    def navigation(self, entry_id: str, title: str, href: str, kind: str, summary: str | None = None,
                   cover_book: int | None = None) -> None:  # fmt: skip
        entry = ET.SubElement(self.root, _q("", "entry"))
        _text(entry, "id", entry_id)
        _text(entry, "title", title)
        _text(entry, "updated", _stamp(None))
        if summary:
            _text(entry, "content", summary, type="text")
        _link(entry, "subsection", href, kind)
        if cover_book is not None:
            _link(
                entry,
                "http://opds-spec.org/image/thumbnail",
                f"/opds/books/{cover_book}/cover?size=medium",
                "image/jpeg",
            )

    def book(self, book: Book, progress: ReadingProgress | None) -> None:
        meta = book.book_metadata
        entry = ET.SubElement(self.root, _q("", "entry"))
        _text(entry, "id", f"urn:kodex:book:{book.id}")
        _text(entry, "title", files.title(book))
        _text(entry, "updated", _stamp(book.updated_at))
        for name in (meta.authors if meta else None) or []:
            author = ET.SubElement(entry, _q("", "author"))
            _text(author, "name", name)
        if meta is not None:
            if meta.language:
                _text(entry, "language", meta.language, "dc")
            if meta.publisher:
                _text(entry, "publisher", meta.publisher, "dc")
            if meta.published_year:
                _text(entry, "issued", str(meta.published_year), "dc")
            for genre in meta.genres or []:
                ET.SubElement(entry, _q("", "category"), {"term": genre, "label": genre})
            if meta.summary:
                _text(entry, "summary", meta.summary, type="text")
        if book.series is not None:
            ET.SubElement(entry, _q("", "category"), {"term": book.series.title, "label": book.series.title,
                                                       "scheme": "urn:kodex:series"})  # fmt: skip
        mime = MIME_TYPES.get(book.file_format)
        if mime is not None:
            _link(entry, "http://opds-spec.org/acquisition", f"/opds/books/{book.id}/file", mime,
                  length=str(book.file_size), title=files.filename(book))  # fmt: skip
        _link(entry, "http://opds-spec.org/image", f"/opds/books/{book.id}/cover?size=large", "image/jpeg")
        _link(entry, "http://opds-spec.org/image/thumbnail", f"/opds/books/{book.id}/cover?size=medium", "image/jpeg")
        if book.file_format in PAGE_BASED_FORMATS and book.page_count:
            stream = _link(entry, PSE_STREAM, f"/opds/books/{book.id}/pages/{{pageNumber}}?width={{maxWidth}}",
                           "image/jpeg")  # fmt: skip
            stream.set(_q("pse", "count"), str(book.page_count))
            last = files.last_page(book, progress)
            if last is not None and progress is not None:
                stream.set(_q("pse", "lastRead"), str(last))
                stream.set(_q("pse", "lastReadDate"), _stamp(progress.last_read_at))

    def response(self) -> Response:
        body = ET.tostring(self.root, encoding="utf-8", xml_declaration=True)
        return Response(body, media_type=self.kind)


def _books(feed: Feed, db: Session, user: User, books: catalog.Page[Book]) -> Response:
    progress = catalog.progress(db, user.id, [b.id for b in books.items])
    for book in books.items:
        feed.book(book, progress.get(book.id))
    return feed.response()


def _series_entries(feed: Feed, db: Session, series: catalog.Page[Series]) -> None:
    covers = catalog.first_book(db, [s.id for s in series.items])
    for item in series.items:
        feed.navigation(f"urn:kodex:series:{item.id}", item.title, f"/opds/series/{item.id}", ACQUISITION,
                        summary=item.summary, cover_book=covers.get(item.id))  # fmt: skip


@router.get("/")
def root(db: Session = Depends(get_db), _user: User = Depends(get_current_user_via_opds_token)) -> Response:
    feed = Feed("urn:kodex:root", "Kodex", "/opds/", NAVIGATION)
    feed.navigation("urn:kodex:reading", "Läser nu", "/opds/reading", ACQUISITION)
    feed.navigation("urn:kodex:latest", "Nytt", "/opds/latest", ACQUISITION)
    feed.navigation("urn:kodex:followed", "Följda serier", "/opds/followed", NAVIGATION)
    for library in catalog.libraries(db):
        feed.navigation(f"urn:kodex:library:{library.id}", library.name, f"/opds/libraries/{library.id}", NAVIGATION)
    return feed.response()


@router.get("/reading")
def reading(page: int = Query(1, ge=1), db: Session = Depends(get_db),
            user: User = Depends(get_current_user_via_opds_token)) -> Response:  # fmt: skip
    books = catalog.reading(db, user.id, page)
    return _books(Feed("urn:kodex:reading", "Läser nu", "/opds/reading", ACQUISITION, books), db, user, books)


@router.get("/latest")
def latest(page: int = Query(1, ge=1), db: Session = Depends(get_db),
           user: User = Depends(get_current_user_via_opds_token)) -> Response:  # fmt: skip
    books = catalog.latest(db, page)
    return _books(Feed("urn:kodex:latest", "Nytt", "/opds/latest", ACQUISITION, books), db, user, books)


@router.get("/followed")
def followed(page: int = Query(1, ge=1), db: Session = Depends(get_db),
             _user: User = Depends(get_current_user_via_opds_token)) -> Response:  # fmt: skip
    series = catalog.followed(db, page)
    feed = Feed("urn:kodex:followed", "Följda serier", "/opds/followed", NAVIGATION, series)
    _series_entries(feed, db, series)
    return feed.response()


@router.get("/libraries/{library_id}")
def library(library_id: int, page: int = Query(1, ge=1), db: Session = Depends(get_db),
            user: User = Depends(get_current_user_via_opds_token)) -> Response:  # fmt: skip
    found = catalog.library(db, library_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such library")
    series = catalog.series_of(db, library_id, page)
    feed = Feed(f"urn:kodex:library:{library_id}", found.name, f"/opds/libraries/{library_id}", NAVIGATION, series)
    _series_entries(feed, db, series)
    if page == 1:
        loose = catalog.loose_books(db, library_id)
        progress = catalog.progress(db, user.id, [b.id for b in loose])
        for book in loose:
            feed.book(book, progress.get(book.id))
    return feed.response()


@router.get("/series/{series_id}")
def series(series_id: int, page: int = Query(1, ge=1), db: Session = Depends(get_db),
           user: User = Depends(get_current_user_via_opds_token)) -> Response:  # fmt: skip
    found = catalog.series(db, series_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such series")
    books = catalog.books_of(db, series_id, page)
    feed = Feed(f"urn:kodex:series:{series_id}", found.title, f"/opds/series/{series_id}", ACQUISITION, books)
    return _books(feed, db, user, books)


@router.get("/search")
def search(q: str = Query("", max_length=200), page: int = Query(1, ge=1), db: Session = Depends(get_db),
           user: User = Depends(get_current_user_via_opds_token)) -> Response:  # fmt: skip
    books = catalog.search(db, q, page)
    feed = Feed(f"urn:kodex:search:{quote(q)}", f"Sök: {q}", "/opds/search", ACQUISITION, books, q=q)
    return _books(feed, db, user, books)


@router.get("/search-description.xml")
def search_description() -> Response:
    root = ET.Element("{http://a9.com/-/spec/opensearch/1.1/}OpenSearchDescription")
    for tag, value in (("ShortName", "Kodex"), ("Description", "Sök i Kodex"), ("InputEncoding", "UTF-8"),
                       ("OutputEncoding", "UTF-8")):  # fmt: skip
        ET.SubElement(root, f"{{{NAMESPACES['opensearch']}}}{tag}").text = value
    ET.SubElement(root, f"{{{NAMESPACES['opensearch']}}}Url", {"type": ACQUISITION,
                                                                 "template": "/opds/search?q={searchTerms}"})  # fmt: skip
    body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(body, media_type="application/opensearchdescription+xml")


@router.get("/books/{book_id}/file")
def book_file(book_id: int, db: Session = Depends(get_db),
              _user: User = Depends(get_current_user_via_opds_token)) -> FileResponse:  # fmt: skip
    return files.download(db, book_id)


@router.get("/books/{book_id}/cover")
def cover(book_id: int, size: Literal["small", "medium", "large"] = "large", db: Session = Depends(get_db),
          _user: User = Depends(get_current_user_via_opds_token)) -> Response:  # fmt: skip
    return files.cover(db, book_id, size)


@router.get("/books/{book_id}/pages/{index}")
def page(book_id: int, index: int, request: Request, width: str | None = Query(None, max_length=16),
         db: Session = Depends(get_db), user: User = Depends(get_current_user_via_opds_token)) -> Response:  # fmt: skip
    """A page for PSE; ``width`` is the client's {maxWidth}, which some send
    unfilled. Fetching a page is how a PSE client says where it is."""
    max_width = int(width) if width and width.isdigit() and int(width) >= 64 else None
    book, response = files.page(db, book_id, index, max_width, get_settings().covers_dir)
    reports.page_fetched(db, user.id, book, index, request)
    return response
