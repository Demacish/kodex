"""B5 — release calendar / pull-list, aggregated across every followed
series' SeriesReleaseEvent rows (see app/enrichment/release_check.py's
_sync_release_events for how those get populated — the weekly followed-
series check, Comic Vine only for now).
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.release_event import SeriesReleaseEvent
from app.models.series import Series
from app.models.user import User
from app.schemas.release_event import ReleaseEventOut, ReleaseEventStatus

router = APIRouter(prefix="/releases", tags=["releases"])


def compute_status(event: SeriesReleaseEvent) -> ReleaseEventStatus:
    if event.owned_book_id is not None:
        return "owned"
    if event.store_date is not None and event.store_date > dt.date.today():
        return "unreleased"
    return "released"


def release_event_out(event: SeriesReleaseEvent, *, series_title: str) -> dict:
    return {
        "id": event.id,
        "series_id": event.series_id,
        "series_title": series_title,
        "external_issue_id": event.external_issue_id,
        "provider": event.provider,
        "issue_number": event.issue_number,
        "title": event.title,
        "store_date": event.store_date,
        "cover_date": event.cover_date,
        "owned_book_id": event.owned_book_id,
        "dismissed": event.dismissed,
        "status": compute_status(event),
    }


@router.get("", response_model=list[ReleaseEventOut])
def list_releases(
    status: ReleaseEventStatus | None = None,
    include_dismissed: bool = Query(default=False),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[dict]:
    """Pull-list across every followed series — see release_check.py's
    weekly sync for how SeriesReleaseEvent rows get here in the first
    place. `status` filters client-relevant computed status; unfiltered
    (the default) returns everything, sorted soonest/most-recent first
    (nulls — a Comic Vine issue with no known store_date yet — last).
    """
    rows = (
        db.query(SeriesReleaseEvent, Series.title)
        .join(Series, Series.id == SeriesReleaseEvent.series_id)
        .filter(Series.is_following.is_(True))
        .all()
    )
    if not include_dismissed:
        rows = [(event, title) for event, title in rows if not event.dismissed]

    items = [release_event_out(event, series_title=title) for event, title in rows]
    if status is not None:
        items = [item for item in items if item["status"] == status]

    items.sort(key=lambda item: (item["store_date"] is None, item["store_date"] or dt.date.max, item["series_title"]))
    return items


@router.post("/{event_id}/dismiss", response_model=ReleaseEventOut)
def dismiss_release(event_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)) -> dict:
    """Hides one event from the pull-list without pretending it's owned —
    see SeriesReleaseEvent.dismissed's own docstring. Any logged-in user,
    not admin-only: this is closer to a shared household preference (like
    following a series itself) than a destructive/management action.
    """
    event = db.get(SeriesReleaseEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Release event not found")
    event.dismissed = True
    db.add(event)
    db.commit()
    db.refresh(event)
    series_title = db.get(Series, event.series_id).title
    return release_event_out(event, series_title=series_title)
