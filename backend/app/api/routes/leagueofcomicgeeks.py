"""Admin-only link flow for League of Comic Geeks events — see
app/enrichment/leagueofcomicgeeks.py's own docstring for why this is a
paste-a-link flow (no search: LoCG has no public API, and the site itself
can't be queried by name from here), same shape as app/api/routes/cbl.py
otherwise.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.enrichment import leagueofcomicgeeks
from app.models.collection import Collection
from app.models.enums import CollectionType
from app.models.story_arc import StoryArc
from app.models.user import User
from app.schemas.story_arc import StoryArcOut
from app.workers.queue import get_enrichment_queue
from app.workers.tasks import refresh_story_arc_task

router = APIRouter(prefix="/leagueofcomicgeeks", tags=["leagueofcomicgeeks"])


class LocgPreviewIn(BaseModel):
    url: str


class LocgPreviewOut(BaseModel):
    event_id: int
    name: str


@router.post("/preview", response_model=LocgPreviewOut)
def preview(payload: LocgPreviewIn, _admin: User = Depends(require_admin)) -> LocgPreviewOut:
    """Resolves a pasted URL to an event id + name, for the admin to
    confirm before linking — mirrors picking a result in the CBL search,
    just with one candidate instead of a list since there's nothing to
    search against."""
    event_id = leagueofcomicgeeks.parse_event_id(payload.url)
    if event_id is None:
        raise HTTPException(status_code=400, detail="Kunde inte hitta ett event-id i den länken")
    try:
        name = leagueofcomicgeeks.fetch_event_name(event_id)
    except leagueofcomicgeeks.LeagueOfComicGeeksError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not name:
        raise HTTPException(status_code=404, detail="Hittade inget event med det id:t")
    return LocgPreviewOut(event_id=event_id, name=name)


class LocgLinkIn(BaseModel):
    event_id: int
    name: str


@router.post("/link", response_model=StoryArcOut, status_code=201)
def link(payload: LocgLinkIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> StoryArc:
    """Links one LoCG event to a (new or existing) Collection, then
    immediately enqueues the first roster fetch — same idempotent
    match-by-name-and-rule check and same reasoning as cbl.py's link()."""
    existing = db.query(StoryArc).filter(StoryArc.locg_event_id == payload.event_id).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Det här eventet är redan länkat")

    rule = {"field": "story_arcs", "value": payload.name}
    collection = (
        db.query(Collection)
        .filter(Collection.name == payload.name, Collection.collection_type == CollectionType.SMART)
        .filter(Collection.rule.op("->>")("value") == payload.name)
        .one_or_none()
    )
    if collection is None:
        collection = Collection(name=payload.name, collection_type=CollectionType.SMART, rule=rule, owner_user_id=None)
        db.add(collection)
        db.flush()

    story_arc = StoryArc(name=payload.name, locg_event_id=payload.event_id, collection_id=collection.id)
    db.add(story_arc)
    db.commit()
    db.refresh(story_arc)

    get_enrichment_queue().enqueue(refresh_story_arc_task, story_arc.id, job_timeout="10m")
    return story_arc
