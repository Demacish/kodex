"""Admin-only browse/search + link flow for CBL-ReadingLists — see
app/enrichment/cbl.py's own docstring for why this needs a dedicated
search+link flow instead of fitting the automatic per-book discovery
path Comic Vine/Metron use (GET .../story-arc/refresh in collections.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import get_settings
from app.database import get_db
from app.enrichment import cbl, comicvine
from app.models.collection import Collection
from app.models.enums import CollectionType
from app.models.story_arc import StoryArc
from app.models.user import User
from app.schemas.story_arc import StoryArcOut
from app.workers.queue import get_enrichment_queue
from app.workers.tasks import refresh_story_arc_task

router = APIRouter(prefix="/cbl", tags=["cbl"])


class CblSearchResult(BaseModel):
    path: str
    name: str
    publisher: str


@router.get("/search", response_model=list[CblSearchResult])
def search(q: str, _admin: User = Depends(require_admin)) -> list[CblSearchResult]:
    results = cbl.search_reading_lists(q)
    return [CblSearchResult(path=r.path, name=r.name, publisher=r.publisher) for r in results]


class CblLinkIn(BaseModel):
    path: str
    name: str


@router.post("/link", response_model=StoryArcOut, status_code=201)
def link(payload: CblLinkIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> StoryArc:
    """Links one CBL reading list to a (new or existing, same idempotent
    match-by-name-and-rule check as _ensure_arc_collections uses)
    Collection, then immediately enqueues the first roster fetch so the
    collection is useful right away instead of showing an empty roster
    until someone happens to click refresh.
    """
    existing = db.query(StoryArc).filter(StoryArc.cbl_path == payload.path).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Den här läslistan är redan länkad")

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

    # Best-effort synopsis — CBL itself carries no description (see
    # cbl.py's own docstring), so this searches Comic Vine's story arcs
    # by name and takes the description if a plausible match turns up.
    # Never blocks linking: no key configured, no match, or a Comic Vine
    # hiccup all just mean no synopsis, not a failed link (2026-09-11,
    # requested).
    description = None
    settings = get_settings()
    if settings.comicvine_api_key:
        try:
            description = comicvine.search_story_arc_description(payload.name, settings.comicvine_api_key)
        except Exception:  # noqa: BLE001 - decoration, must never break linking
            description = None

    story_arc = StoryArc(name=payload.name, cbl_path=payload.path, collection_id=collection.id, description=description)
    db.add(story_arc)
    db.commit()
    db.refresh(story_arc)

    get_enrichment_queue().enqueue(refresh_story_arc_task, story_arc.id, job_timeout="10m")
    return story_arc
