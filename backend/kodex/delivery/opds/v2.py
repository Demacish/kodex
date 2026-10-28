"""OPDS 2.0 (JSON), with the Progression draft for reading progress.

    /opds/v2/catalog                 the start: navigation and groups
    /opds/v2/reading, /latest        publications
    /opds/v2/followed                followed series
    /opds/v2/libraries/{id}          a library's series
    /opds/v2/series/{id}             a series' books
    /opds/v2/search{?query}          books by title, series or author
    /opds/v2/books/{id}/progression  GET/PUT the position (Readium's
                                     Progression draft, as Cantook and
                                     Komga use it)

Files, covers and pages are the Atom catalog's (/opds/books/...)."""

from __future__ import annotations

import datetime as dt
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user_via_opds_token
from app.config import get_settings
from app.database import get_db
from app.models.book import Book
from app.models.enums import PAGE_BASED_FORMATS, BookFormat
from app.models.reading_progress import ReadingProgress
from app.models.series import Series
from app.models.user import User
from app.progress.sync import FINISHED_AT, follow_series
from kodex.delivery.opds import catalog, files, reports
from kodex.delivery.opds.atom import MIME_TYPES
from kodex.reading import journal, positions

router = APIRouter(prefix="/opds/v2", tags=["opds2"])

OPDS = "application/opds+json"
PUBLICATION = "application/opds-publication+json"
PROGRESSION = "application/vnd.readium.progression+json"
PROGRESSION_REL = "http://www.cantook.com/api/progression"


class Link(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    href: str
    type: str | None = None
    rel: str | list[str] | None = None
    title: str | None = None
    templated: bool | None = None
    properties: dict[str, Any] | None = None


class Feed(BaseModel):
    metadata: dict[str, Any]
    links: list[Link]
    navigation: list[Link] | None = None
    publications: list[dict[str, Any]] | None = None
    groups: list[dict[str, Any]] | None = None


def _absolute(value: Any, base: str) -> Any:
    """OPDS 2 wants absolute links (a feed's self link must be one)."""
    if isinstance(value, dict):
        return {k: base + v if k == "href" and isinstance(v, str) and v.startswith("/") else _absolute(v, base)
                for k, v in value.items()}  # fmt: skip
    if isinstance(value, list):
        return [_absolute(v, base) for v in value]
    return value


def _base_url(request: Request) -> str:
    return get_settings().public_app_url.rstrip("/") or str(request.base_url).rstrip("/")


def _response(request: Request, feed: Feed, media_type: str = OPDS) -> JSONResponse:
    return JSONResponse(_absolute(feed.model_dump(exclude_none=True), _base_url(request)), media_type=media_type)


def _base(
    path: str, title: str, page: catalog.Page[Any] | None = None, **params: str
) -> tuple[dict[str, Any], list[Link]]:
    def href(number: int | None = None) -> str:
        query = {**params, **({"page": str(number)} if number and number > 1 else {})}
        return path + ("?" + urlencode(query) if query else "")

    metadata: dict[str, Any] = {"title": title}
    links = [Link(rel="self", href=href(page.number if page else None), type=OPDS),
             Link(rel="start", href="/opds/v2/catalog", type=OPDS),
             Link(rel="search", href="/opds/v2/search{?query}", type=OPDS, templated=True)]  # fmt: skip
    if page is not None:
        metadata.update(numberOfItems=page.total, itemsPerPage=page.size, currentPage=page.number)
        if page.number > 1:
            links.append(Link(rel="previous", href=href(page.number - 1), type=OPDS))
        if page.number < page.last:
            links.append(Link(rel="next", href=href(page.number + 1), type=OPDS))
        if page.last > 1:
            links += [Link(rel="first", href=href(), type=OPDS), Link(rel="last", href=href(page.last), type=OPDS)]
    return metadata, links


def _stamp(value: dt.datetime | None) -> str | None:
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z") if value else None


def publication(book: Book, progress: ReadingProgress | None) -> dict[str, Any]:
    meta = book.book_metadata
    metadata: dict[str, Any] = {
        "@type": "http://schema.org/Book" if book.file_format == BookFormat.EPUB else "http://schema.org/ComicIssue",
        "identifier": f"urn:kodex:book:{book.id}",
        "title": files.title(book),
        "modified": _stamp(book.updated_at),
    }
    if meta is not None:
        if meta.authors:
            metadata["author"] = [{"name": name} for name in meta.authors]
        if meta.language:
            metadata["language"] = meta.language
        if meta.publisher:
            metadata["publisher"] = meta.publisher
        if meta.published_year:
            metadata["published"] = str(meta.published_year)
        if meta.summary:
            metadata["description"] = meta.summary
        if meta.genres:
            metadata["subject"] = [{"name": g} for g in meta.genres]
    if book.series is not None:
        series: dict[str, Any] = {"name": book.series.title, "links": [{"href": f"/opds/v2/series/{book.series.id}",
                                                                         "type": OPDS}]}  # fmt: skip
        if book.number is not None:
            series["position"] = book.number
        metadata["belongsTo"] = {"series": [series]}
    if book.page_count:
        metadata["numberOfPages"] = book.page_count
    links: list[dict[str, Any]] = [
        {"rel": "self", "href": f"/opds/v2/books/{book.id}", "type": PUBLICATION},
        {"rel": PROGRESSION_REL, "href": f"/opds/v2/books/{book.id}/progression", "type": PROGRESSION},
    ]
    mime = MIME_TYPES.get(book.file_format)
    if mime is not None:
        links.append({"rel": "http://opds-spec.org/acquisition", "href": f"/opds/books/{book.id}/file", "type": mime,
                      "properties": {"length": book.file_size}})  # fmt: skip
    images = [{"href": f"/opds/books/{book.id}/cover?size={size}", "type": "image/jpeg", "height": edge}
              for size, edge in (("small", 200), ("medium", 400), ("large", 1000))]  # fmt: skip
    entry: dict[str, Any] = {"metadata": metadata, "links": links, "images": images}
    if progress is not None and progress.progress_percent > 0:
        entry["metadata"]["readingProgress"] = round(progress.progress_percent / 100, 4)
    return entry


def _publications(db: Session, user: User, books: catalog.Page[Book]) -> list[dict[str, Any]]:
    progress = catalog.progress(db, user.id, [b.id for b in books.items])
    return [publication(b, progress.get(b.id)) for b in books.items]


def _series_links(db: Session, series: catalog.Page[Series]) -> list[Link]:
    return [Link(href=f"/opds/v2/series/{s.id}", title=s.title, type=OPDS, rel="subsection") for s in series.items]


@router.get("/catalog")
def home(request: Request, db: Session = Depends(get_db),
         user: User = Depends(get_current_user_via_opds_token)) -> JSONResponse:  # fmt: skip
    metadata, links = _base("/opds/v2/catalog", "Kodex")
    navigation = [Link(href="/opds/v2/reading", title="Läser nu", type=OPDS),
                  Link(href="/opds/v2/latest", title="Nytt", type=OPDS),
                  Link(href="/opds/v2/followed", title="Följda serier", type=OPDS)]  # fmt: skip
    navigation += [
        Link(href=f"/opds/v2/libraries/{lib.id}", title=lib.name, type=OPDS) for lib in catalog.libraries(db)
    ]
    groups = []
    for title, path, books in (("Läser nu", "/opds/v2/reading", catalog.reading(db, user.id, 1)),
                               ("Nytt", "/opds/v2/latest", catalog.latest(db, 1))):  # fmt: skip
        if books.items:
            groups.append({"metadata": {"title": title, "numberOfItems": books.total},
                           "links": [{"rel": "self", "href": path, "type": OPDS}],
                           "publications": _publications(db, user, catalog.Page(books.items[:10], 1, books.total))})  # fmt: skip
    return _response(request, Feed(metadata=metadata, links=links, navigation=navigation, groups=groups or None))


@router.get("/reading")
def reading(request: Request, page: int = Query(1, ge=1), db: Session = Depends(get_db),
            user: User = Depends(get_current_user_via_opds_token)) -> JSONResponse:  # fmt: skip
    books = catalog.reading(db, user.id, page)
    metadata, links = _base("/opds/v2/reading", "Läser nu", books)
    return _response(request, Feed(metadata=metadata, links=links, publications=_publications(db, user, books)))


@router.get("/latest")
def latest(request: Request, page: int = Query(1, ge=1), db: Session = Depends(get_db),
           user: User = Depends(get_current_user_via_opds_token)) -> JSONResponse:  # fmt: skip
    books = catalog.latest(db, page)
    metadata, links = _base("/opds/v2/latest", "Nytt", books)
    return _response(request, Feed(metadata=metadata, links=links, publications=_publications(db, user, books)))


@router.get("/followed")
def followed(request: Request, page: int = Query(1, ge=1), db: Session = Depends(get_db),
             _user: User = Depends(get_current_user_via_opds_token)) -> JSONResponse:  # fmt: skip
    series = catalog.followed(db, page)
    metadata, links = _base("/opds/v2/followed", "Följda serier", series)
    return _response(request, Feed(metadata=metadata, links=links, navigation=_series_links(db, series)))


@router.get("/libraries/{library_id}")
def library(library_id: int, request: Request, page: int = Query(1, ge=1), db: Session = Depends(get_db),
            user: User = Depends(get_current_user_via_opds_token)) -> JSONResponse:  # fmt: skip
    found = catalog.library(db, library_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such library")
    series = catalog.series_of(db, library_id, page)
    metadata, links = _base(f"/opds/v2/libraries/{library_id}", found.name, series)
    loose = catalog.loose_books(db, library_id) if page == 1 else []
    publications = _publications(db, user, catalog.Page(loose, 1, len(loose))) if loose else None
    return _response(request, Feed(metadata=metadata, links=links, navigation=_series_links(db, series) or None,
                          publications=publications))  # fmt: skip


@router.get("/series/{series_id}")
def series(series_id: int, request: Request, page: int = Query(1, ge=1), db: Session = Depends(get_db),
           user: User = Depends(get_current_user_via_opds_token)) -> JSONResponse:  # fmt: skip
    found = catalog.series(db, series_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such series")
    books = catalog.books_of(db, series_id, page)
    metadata, links = _base(f"/opds/v2/series/{series_id}", found.title, books)
    return _response(request, Feed(metadata=metadata, links=links, publications=_publications(db, user, books)))


@router.get("/search")
def search(request: Request, query: str = Query("", max_length=200), page: int = Query(1, ge=1), db: Session = Depends(get_db),
           user: User = Depends(get_current_user_via_opds_token)) -> JSONResponse:  # fmt: skip
    books = catalog.search(db, query, page)
    metadata, links = _base("/opds/v2/search", f"Sök: {query}", books, query=query)
    return _response(request, Feed(metadata=metadata, links=links, publications=_publications(db, user, books)))


@router.get("/books/{book_id}")
def book(book_id: int, request: Request, db: Session = Depends(get_db),
         user: User = Depends(get_current_user_via_opds_token)) -> JSONResponse:  # fmt: skip
    found = db.get(Book, book_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such book")
    entry = _absolute(publication(found, journal.current(db, user.id, book_id)), _base_url(request))
    return JSONResponse(entry, media_type=PUBLICATION)


class Locations(BaseModel):
    model_config = ConfigDict(extra="allow")

    position: int | None = None
    progression: float | None = Field(default=None, ge=0, le=1)
    totalProgression: float | None = Field(default=None, ge=0, le=1)


class Locator(BaseModel):
    model_config = ConfigDict(extra="allow")

    href: str | None = None
    type: str | None = None
    locations: Locations = Field(default_factory=Locations)


class Device(BaseModel):
    id: str = Field(default="", max_length=64)
    name: str = Field(default="", max_length=100)


class Progression(BaseModel):
    """Readium's Progression draft (also Cantook's and Komga's)."""

    model_config = ConfigDict(extra="allow")

    modified: dt.datetime | None = None
    device: Device | None = None
    locator: Locator = Field(default_factory=Locator)


@router.get("/books/{book_id}/progression")
def get_progression(book_id: int, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user_via_opds_token)) -> Response:  # fmt: skip
    found = db.get(Book, book_id)
    current = journal.current(db, user.id, book_id) if found is not None else None
    if found is None or current is None:
        return Response(status_code=204)
    fraction = round(current.progress_percent / 100, 6)
    locations: dict[str, Any] = {"totalProgression": fraction, "progression": fraction}
    index = positions.page_index(found, current.locator_kind, current.position, current.progress_percent)
    href = f"/opds/books/{book_id}/file"
    if found.file_format in PAGE_BASED_FORMATS and index is not None:
        locations["position"] = index + 1
        href = f"/opds/books/{book_id}/pages/{index}"
    body = {"modified": _stamp(current.last_read_at),
            "device": {"id": current.device_id or "", "name": current.device_name or "Kodex"},
            "locator": {"href": href, "type": "image/jpeg" if "pages" in href else MIME_TYPES.get(found.file_format),
                        "locations": locations}}  # fmt: skip
    return JSONResponse(_absolute(body, _base_url(request)), media_type=PROGRESSION)


@router.put("/books/{book_id}/progression", status_code=204)
def put_progression(book_id: int, body: Progression, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user_via_opds_token)) -> None:  # fmt: skip
    found = db.get(Book, book_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such book")
    device_id, device_name = reports.device(request)
    if body.device is not None and body.device.id:
        device_id, device_name = f"{device_id}:{body.device.id}"[:64], body.device.name or device_name
    where = body.locator.locations
    fraction = where.totalProgression if where.totalProgression is not None else where.progression or 0.0
    kind: str = "percent"
    position: str | None = None
    if positions.paged(found) and where.position is not None and where.position >= 1:
        kind, position = (
            ("pdf", str(where.position)) if found.file_format == BookFormat.PDF else ("page", str(where.position - 1))
        )
        if found.page_count and where.totalProgression is None:
            fraction = where.position / found.page_count
    journal.report(db, user.id, found, journal.Report(
        position=position, locator_kind=kind, percent=round(fraction * 100, 2), is_finished=fraction >= FINISHED_AT,
        device_id=device_id, device_name=device_name[:100], client_at=body.modified))  # fmt: skip
    follow_series(db, found)
    db.commit()
