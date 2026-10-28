"""The Kobo sync endpoints, at the address a Kobo e-reader is pointed to:
``api_endpoint=https://<server>/kobo/<Kobo key>`` in the device's
``.kobo/Kobo/Kobo eReader.conf``. They answer the store protocol for the
library (sync, metadata, reading state, downloads, covers); everything else
goes on to Kobo's store (kodex.reading.kobo.store).

The device needs HTTPS, and sends long headers: a reverse proxy in front
needs room for them (nginx: large_client_header_buffers; Caddy is fine)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path as FsPath
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.book import Book
from app.models.collection import Collection, collection_books
from app.models.enums import BookFormat, CollectionType
from app.models.user import User
from app.progress.sync import FINISHED_AT, follow_series
from kodex.core.auth import keys
from kodex.core.auth.models import ApiKey
from kodex.formats import kepub
from kodex.library import covers
from kodex.library.paths import OutsideLibraries, within
from kodex.reading import journal, pages
from kodex.reading.kobo import store, sync
from kodex.reading.models import KoboBook, KoboDevice

router = APIRouter(prefix="/kobo/{token}", tags=["kobo"], include_in_schema=False)


@dataclass(frozen=True)
class Caller:
    user: User
    key: ApiKey
    device: KoboDevice

    @property
    def device_id(self) -> str:
        return f"kobo-{self.key.id}"


def default_collection(db: Session, user: User) -> Collection:
    """The user's "Kobo" collection, made when missing."""
    query = select(Collection).where(Collection.owner_user_id == user.id, Collection.name == "Kobo",
                                     Collection.collection_type == CollectionType.MANUAL)  # fmt: skip
    found = db.scalars(query).first()
    if found is None:
        found = Collection(name="Kobo", collection_type=CollectionType.MANUAL, owner_user_id=user.id)
        db.add(found)
        db.flush()
    return found


def device_for(db: Session, key: ApiKey, user: User) -> KoboDevice:
    found = db.scalars(select(KoboDevice).where(KoboDevice.api_key_id == key.id)).first()
    if found is None:
        found = KoboDevice(api_key_id=key.id, collection_id=default_collection(db, user).id)
        db.add(found)
        db.flush()
    return found


def caller(token: str = Path(max_length=128), db: Session = Depends(get_db)) -> Caller:
    record = keys.record_for_key(db, token, ("kobo",))
    user = keys.used(db, record) if record is not None else None
    if record is None or user is None:
        raise HTTPException(status_code=401, detail="Unknown Kobo key")
    device = device_for(db, record, user)
    db.commit()
    return Caller(user=user, key=record, device=device)


def _base(request: Request, token: str) -> str:
    root = get_settings().public_app_url.rstrip("/") or str(request.base_url).rstrip("/")
    return f"{root}/kobo/{token}"


def _book(db: Session, value: str) -> Book | None:
    book_id = sync.book_id_of(value)
    return db.get(Book, book_id) if book_id is not None else None


def _file(book: Book) -> FsPath:
    settings = get_settings()
    try:
        path = within(settings.libraries_root, book.library.path, book.file_path)
    except OutsideLibraries as exc:
        raise HTTPException(status_code=404, detail="No such book") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The file is missing")
    return path


def _describer(request: Request, token: str) -> Callable[[Book], dict[str, Any]]:
    base = _base(request, token)
    settings = get_settings()
    converts = kepub.available(settings.kepubify_binary)

    def describe(book: Book) -> dict[str, Any]:
        uuid = sync.book_uuid(book.id)
        return sync.metadata(book, f"{base}/v1/books/{uuid}/file", "KEPUB" if converts else "EPUB", book.file_size)

    return describe


@router.get("/v1/initialization")
def initialization(token: str, request: Request, _caller: Caller = Depends(caller)) -> JSONResponse:
    resources = store.resources(store.forward(request, "/v1/initialization", b""))
    base = _base(request, token)
    resources["image_host"] = base
    resources["image_url_template"] = f"{base}/v1/books/{{ImageId}}/thumbnail/{{Width}}/{{Height}}/false/image.jpg"
    resources["image_url_quality_template"] = (
        f"{base}/v1/books/{{ImageId}}/thumbnail/{{Width}}/{{Height}}/{{Quality}}/{{IsGreyscale}}/image.jpg"
    )
    return JSONResponse({"Resources": resources}, headers={"x-kobo-apitoken": "e30="})


@router.get("/v1/library/sync")
def library_sync(token: str, request: Request, db: Session = Depends(get_db),
                 who: Caller = Depends(caller)) -> JSONResponse:  # fmt: skip
    """This server's books after the store's (when it is asked), a page at
    a time; ``x-kobo-sync: continue`` asks the device to come back."""
    sent_token = sync.Token.parse(request.headers.get("x-kobo-synctoken"))
    store_items: list[Any] = []
    store_more = False
    # The store gets its own token back, never this server's.
    answer = store.forward(request, "/v1/library/sync", b"", {"x-kobo-synctoken": sent_token.store or ""})
    if answer is not None and answer.status_code == 200:
        try:
            body = answer.json()
            store_items = body if isinstance(body, list) else []
            sent_token.store = answer.headers.get("x-kobo-synctoken") or sent_token.store
            store_more = answer.headers.get("x-kobo-sync") == "continue"
        except ValueError:
            pass
    found = sync.changes(db, who.device, who.user.id, sent_token, who.device_id, _describer(request, token))
    db.commit()
    headers = {"x-kobo-synctoken": sent_token.header()}
    if found.more or store_more:
        headers["x-kobo-sync"] = "continue"
    return JSONResponse(store_items + found.items, headers=headers)


@router.get("/v1/library/{book}/metadata")
def book_metadata(token: str, book: str, request: Request, db: Session = Depends(get_db),
                  who: Caller = Depends(caller)) -> Response:  # fmt: skip
    found = _book(db, book)
    if found is None:
        return _onward(request, f"/v1/library/{book}/metadata")
    return JSONResponse([_describer(request, token)(found)])


@router.get("/v1/library/{book}/state")
def get_state(book: str, request: Request, db: Session = Depends(get_db), who: Caller = Depends(caller)) -> Response:
    found = _book(db, book)
    if found is None:
        return _onward(request, f"/v1/library/{book}/state")
    return JSONResponse([sync.reading_state(found, journal.current(db, who.user.id, found.id))])


@router.put("/v1/library/{book}/state")
async def put_state(book: str, request: Request, db: Session = Depends(get_db),
                    who: Caller = Depends(caller)) -> Response:  # fmt: skip
    body = await request.body()
    found = _book(db, book)
    if found is None:
        return _onward(request, f"/v1/library/{book}/state", body)
    try:
        states = (await request.json()).get("ReadingStates") or []
    except ValueError:
        states = []
    results = []
    for state in states:
        if not isinstance(state, dict):
            continue
        bookmark = state.get("CurrentBookmark") or {}
        status = (state.get("StatusInfo") or {}).get("Status")
        percent = float(bookmark.get("ProgressPercent") or 0)
        if status == "Finished":
            percent = 100.0
        position = sync.location(bookmark)
        journal.report(db, who.user.id, found, journal.Report(
            position=position, locator_kind="kobo" if position else "percent", percent=percent,
            is_finished=status == "Finished" or percent / 100 >= FINISHED_AT, device_id=who.device_id,
            device_name=who.key.name))  # fmt: skip
        follow_series(db, found)
        results.append({"EntitlementId": state.get("EntitlementId") or book,
                        "CurrentBookmarkResult": {"Result": "Success"}, "StatisticsResult": {"Result": "Success"},
                        "StatusInfoResult": {"Result": "Success"}})  # fmt: skip
    db.commit()
    return JSONResponse({"RequestResult": "Success", "UpdateResults": results})


@router.delete("/v1/library/{book}")
async def remove_book(book: str, request: Request, db: Session = Depends(get_db),
                      who: Caller = Depends(caller)) -> Response:  # fmt: skip
    """Removing a book on the device takes it out of the device's collection."""
    found = _book(db, book)
    if found is None:
        return _onward(request, f"/v1/library/{book}", await request.body())
    if who.device.collection_id is not None:
        db.execute(delete(collection_books).where(collection_books.c.collection_id == who.device.collection_id,
                                                  collection_books.c.book_id == found.id))  # fmt: skip
    synced = db.get(KoboBook, (who.device.id, found.id))
    if synced is not None:
        synced.removed = True
    db.commit()
    return Response(status_code=204)


@router.get("/v1/books/{book}/file")
def download(book: str, db: Session = Depends(get_db), _who: Caller = Depends(caller)) -> FileResponse:
    found = _book(db, book)
    if found is None or found.file_format != BookFormat.EPUB:
        raise HTTPException(status_code=404, detail="No such book")
    path = _file(found)
    settings = get_settings()
    key = pages.content_key(found, path)
    converted = kepub.cached(settings.kepubify_binary, path, settings.covers_dir, key)
    name = path.stem
    if converted is not None:
        return FileResponse(converted, media_type="application/epub+zip", filename=f"{name}.kepub.epub")
    return FileResponse(path, media_type="application/epub+zip", filename=f"{name}.epub")


@router.get("/v1/books/{image}/thumbnail/{width}/{height}/{rest:path}")
def cover(image: str, width: int, height: int, rest: str, db: Session = Depends(get_db),
          _who: Caller = Depends(caller)) -> Response:  # fmt: skip
    """Covers, ours as JPEG; a store book's from Kobo's image server."""
    found = _book(db, image)
    if found is None:
        return RedirectResponse(f"{store.IMAGES}/{image}/{width}/{height}/{rest}", status_code=307)
    settings = get_settings()
    size = "medium" if max(width, height) <= 400 else "large"
    if not found.cover_key or not covers.cover_file(settings.covers_dir, found.id, size).is_file():
        covers.make(found, settings.libraries_root, settings.covers_dir, force=True)
        db.commit()
    jpeg = covers.jpeg_file(settings.covers_dir, found.id, size)
    if jpeg is None:
        raise HTTPException(status_code=404, detail="This book has no cover")
    return FileResponse(jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


def _onward(request: Request, path: str, body: bytes = b"") -> Response:
    answer = store.forward(request, path, body)
    return store.relay(answer) if answer is not None else store.empty(path)


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def anything_else(path: str, request: Request, _who: Caller = Depends(caller)) -> Response:
    """The store's part: the device's account, purchases, settings."""
    return _onward(request, f"/{path}", await request.body())
