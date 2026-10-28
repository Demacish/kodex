"""The trackers in the web client: connecting accounts, linking series,
and sending what was read now instead of at the next quarter hour."""

from __future__ import annotations

import datetime as dt
import secrets as random
from typing import Literal
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.enums import LibraryType
from app.models.library import Library
from app.models.series import Series
from app.models.user import User
from kodex.core.auth import factors
from kodex.matching.models import SeriesExternalId
from kodex.reading.trackers import push as pushing
from kodex.reading.trackers import secrets
from kodex.reading.trackers.models import TrackerAccount, TrackerLink
from kodex.reading.trackers.services import SERVICES, Identity, Service, Tokens, TrackerError, Unit, service

router = APIRouter(tags=["trackers"])

_PURPOSE = "tracker_oauth"


class TrackerAccountOut(BaseModel):
    username: str
    connected_at: dt.datetime


class TrackerServiceOut(BaseModel):
    name: str
    title: str
    login: Literal["password", "oauth"]
    units: list[Unit]
    configured: bool = Field(description="False when the server lacks the service's client (AniList, MyAnimeList)")
    account: TrackerAccountOut | None


class TrackersOut(BaseModel):
    available: bool = Field(description="False until the server has a SECRET_KEY to keep tokens with")
    services: list[TrackerServiceOut]


class TrackerLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


class TrackerAuthorizeOut(BaseModel):
    url: str


class TrackerHitOut(BaseModel):
    id: str
    title: str
    year: int | None
    url: str | None
    cover: str | None
    volumes: int | None
    chapters: int | None


class TrackerLinkOut(BaseModel):
    remote_id: str
    title: str
    unit: Unit
    sent_progress: int
    sent_at: dt.datetime | None
    error: str | None


class SeriesTrackerOut(BaseModel):
    service: str
    title: str
    units: list[Unit]
    link: TrackerLinkOut | None
    suggested_id: str | None = Field(description="The service's id for the series, from its matched external ids")


class SeriesTrackersOut(BaseModel):
    progress: int = Field(description="What the series counts as read now")
    default_unit: Unit
    trackers: list[SeriesTrackerOut]


class TrackerLinkIn(BaseModel):
    remote_id: str = Field(min_length=1, max_length=64)
    title: str = Field("", max_length=500)
    unit: Unit


def _service(name: str) -> Service:
    impl = service(name)
    if impl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such tracker")
    return impl


def _require_keys() -> None:
    if not secrets.available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The server needs a SECRET_KEY for trackers")


def _account(db: Session, user_id: int, name: str) -> TrackerAccount | None:
    return db.scalars(
        select(TrackerAccount).where(TrackerAccount.user_id == user_id, TrackerAccount.service == name)
    ).first()


def _connected(db: Session, user: User, name: str) -> TrackerAccount:
    account = _account(db, user.id, name)
    if account is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Connect the tracker under Inställningar first")
    return account


def _save_account(db: Session, user: User, impl: Service, tokens: Tokens, identity: Identity) -> TrackerAccount:
    account = _account(db, user.id, impl.name) or TrackerAccount(user_id=user.id, service=impl.name)
    account.remote_user_id = identity.id
    account.username = identity.name[:255]
    pushing.store(account, tokens)
    db.add(account)
    db.commit()
    return account


@router.get("/trackers", response_model=TrackersOut)
def list_trackers(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> TrackersOut:
    accounts = {a.service: a for a in db.scalars(select(TrackerAccount).where(TrackerAccount.user_id == user.id))}
    out = []
    for name, cls in SERVICES.items():
        account = accounts.get(name)
        out.append(TrackerServiceOut(
            name=name, title=cls.title, login=cls.login, units=list(cls.units), configured=cls.configured(),
            account=TrackerAccountOut(username=account.username, connected_at=account.created_at) if account else None))  # fmt: skip
    return TrackersOut(available=secrets.available(), services=out)


@router.post("/trackers/{name}/login", response_model=TrackerAccountOut)
def login_tracker(name: str, body: TrackerLoginIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)) -> TrackerAccountOut:  # fmt: skip
    """Connects a password service (MangaUpdates, Kitsu). The password isn't kept; the service's token is."""
    _require_keys()
    impl = _service(name)
    if impl.login != "password":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{impl.title} connects through its own login page")
    try:
        tokens, identity = impl.sign_in(body.username.strip(), body.password)
    except TrackerError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    account = _save_account(db, user, impl, tokens, identity)
    return TrackerAccountOut(username=account.username, connected_at=account.created_at)


def _origin(request: Request) -> str:
    public = get_settings().public_app_url.rstrip("/")
    if public:
        parts = urlsplit(public)
        return f"{parts.scheme}://{parts.netloc}"
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    return f"{proto}://{request.headers.get('host') or request.url.netloc}"


def _redirect_uri(request: Request, name: str) -> str:
    return f"{_origin(request)}/api/trackers/{name}/callback"


@router.post("/trackers/{name}/authorize", response_model=TrackerAuthorizeOut)
def authorize_tracker(name: str, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)) -> TrackerAuthorizeOut:  # fmt: skip
    """The service's login page for an OAuth service (AniList, MyAnimeList); it comes back to the callback."""
    _require_keys()
    impl = _service(name)
    if impl.login != "oauth":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{impl.title} connects with a username and password")
    if not impl.configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"The server has no {impl.title} client")
    verifier = random.token_urlsafe(64)
    ticket = factors.new_ticket(db, _PURPOSE, user.id, verifier.encode())
    ticket.label = name
    db.commit()
    return TrackerAuthorizeOut(url=impl.authorize_url(_redirect_uri(request, name), ticket.ticket, verifier))


def _back(request: Request, **query: str) -> RedirectResponse:
    return RedirectResponse(
        f"{_origin(request)}/settings?{urlencode(query)}#trackers", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/trackers/{name}/callback", include_in_schema=False)
def tracker_callback(name: str, request: Request, code: str | None = None, state: str | None = None,
                     db: Session = Depends(get_db)) -> RedirectResponse:  # fmt: skip
    """Where the service sends the browser back: the code becomes the account's tokens."""
    impl = _service(name)
    ticket = factors.take(db, state or "", (_PURPOSE,))
    user = db.get(User, ticket.user_id) if ticket is not None and ticket.user_id is not None else None
    if ticket is None or user is None or ticket.label != name or ticket.challenge is None or not code:
        db.commit()
        return _back(request, tracker_error=name)
    try:
        tokens, identity = impl.exchange(code, _redirect_uri(request, name), ticket.challenge.decode())
    except TrackerError:
        db.commit()
        return _back(request, tracker_error=name)
    _save_account(db, user, impl, tokens, identity)
    return _back(request, tracker=name)


@router.delete("/trackers/{name}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_tracker(name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    """Forgets the account and the series linked with it; nothing changes at the service."""
    _service(name)
    for row in db.scalars(select(TrackerLink).where(TrackerLink.user_id == user.id, TrackerLink.service == name)):
        db.delete(row)
    account = _account(db, user.id, name)
    if account is not None:
        db.delete(account)
    db.commit()


@router.get("/trackers/{name}/search", response_model=list[TrackerHitOut])
def search_tracker(name: str, q: str = Query(min_length=2, max_length=200), db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> list[TrackerHitOut]:  # fmt: skip
    impl = _service(name)
    account = _connected(db, user, name)
    try:
        hits = impl.search(pushing.tokens_of(db, account, impl), q)
    except TrackerError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return [TrackerHitOut(**vars(hit)) for hit in hits]


def _series(db: Session, series_id: int) -> Series:
    found = db.get(Series, series_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Series not found")
    return found


def _default_unit(db: Session, series: Series) -> Unit:
    library = db.get(Library, series.library_id)
    return "volume" if library is not None and library.library_type == LibraryType.MANGA else "chapter"


def _link_out(link: TrackerLink) -> TrackerLinkOut:
    unit: Unit = "volume" if link.unit == "volume" else "chapter"
    return TrackerLinkOut(remote_id=link.remote_id, title=link.title, unit=unit, sent_progress=link.sent_progress,
                          sent_at=link.sent_at, error=link.error)  # fmt: skip


@router.get("/series/{series_id}/trackers", response_model=SeriesTrackersOut)
def series_trackers(
    series_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> SeriesTrackersOut:
    """The user's connected trackers for a series: linked, or with the id the matcher found there."""
    series = _series(db, series_id)
    connected = {a.service for a in db.scalars(select(TrackerAccount).where(TrackerAccount.user_id == user.id))}
    links = {link.service: link for link in db.scalars(
        select(TrackerLink).where(TrackerLink.user_id == user.id, TrackerLink.series_id == series_id))}  # fmt: skip
    external = db.scalars(select(SeriesExternalId).where(SeriesExternalId.series_id == series_id)
                          .order_by(SeriesExternalId.is_primary.desc(), SeriesExternalId.id)).all()  # fmt: skip
    out = []
    for name, cls in SERVICES.items():
        if name not in connected:
            continue
        suggested = next((e.external_id for e in external if e.provider in cls.external_ids), None)
        link = links.get(name)
        out.append(SeriesTrackerOut(service=name, title=cls.title, units=list(cls.units),
                                    link=_link_out(link) if link else None, suggested_id=suggested))  # fmt: skip
    return SeriesTrackersOut(progress=pushing.progress(db, user.id, series_id), default_unit=_default_unit(db, series),
                             trackers=out)  # fmt: skip


@router.put("/series/{series_id}/trackers/{name}", response_model=TrackerLinkOut)
def link_series(series_id: int, name: str, body: TrackerLinkIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> TrackerLinkOut:  # fmt: skip
    """Links the series to the service's entry and sends its progress at once."""
    series = _series(db, series_id)
    impl = _service(name)
    _connected(db, user, name)
    if body.unit not in impl.units:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{impl.title} counts {', '.join(impl.units)}s")
    link = db.scalars(select(TrackerLink).where(TrackerLink.user_id == user.id, TrackerLink.series_id == series_id,
                                                TrackerLink.service == name)).first()  # fmt: skip
    if link is None or link.remote_id != body.remote_id or link.unit != body.unit:
        if link is not None:
            db.delete(link)
            db.flush()
        link = TrackerLink(user_id=user.id, series_id=series_id, service=name, remote_id=body.remote_id,
                           title=(body.title or series.title)[:500], unit=body.unit, sent_progress=0)  # fmt: skip
        db.add(link)
        db.commit()
    pushing.push(db, link, impl, force=True)
    db.refresh(link)
    return _link_out(link)


@router.delete("/series/{series_id}/trackers/{name}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_series(
    series_id: int, name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> None:
    for link in db.scalars(select(TrackerLink).where(TrackerLink.user_id == user.id, TrackerLink.series_id == series_id,
                                                     TrackerLink.service == name)):  # fmt: skip
        db.delete(link)
    db.commit()


@router.post("/series/{series_id}/trackers/sync", response_model=list[TrackerLinkOut])
def sync_series(
    series_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[TrackerLinkOut]:
    """Sends the series' progress to every linked tracker now."""
    _series(db, series_id)
    links = db.scalars(
        select(TrackerLink).where(TrackerLink.user_id == user.id, TrackerLink.series_id == series_id)
    ).all()
    for link in links:
        pushing.push(db, link, force=True)
    for link in links:
        db.refresh(link)
    return [_link_out(link) for link in links]
