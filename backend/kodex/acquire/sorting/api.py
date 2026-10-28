"""The sorting review queue — /admin's "Sortering" panel talks to this.

Flow: POST /sorting/scan classifies new arrivals in the intake library
(see kodex/acquire/sorting/classifier.py), high-confidence ones come back already
RESOLVED, uncertain ones are PENDING. GET /sorting lists both so the admin
can review — for PENDING items, POST /sorting/{id}/resolve sets the type
by hand (or POST /sorting/{id}/skip to leave it where it is). Nothing
physically moves until POST /sorting/apply, which only ever touches
RESOLVED items.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models.enums import SortingStatus
from app.models.sorting import SortingItem
from app.models.user import User
from app.schemas.common import JobQueuedOut
from app.schemas.sorting import SortingItemOut, SortingResolve
from app.workers.queue import get_scan_queue
from app.workers.tasks import sorting_apply_task, sorting_scan_task, write_comicinfo_task

router = APIRouter(prefix="/sorting", tags=["sorting"])


@router.get("", response_model=list[SortingItemOut])
def list_sorting_items(_admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[SortingItem]:
    return (
        db.query(SortingItem)
        .filter(SortingItem.status.in_([SortingStatus.PENDING, SortingStatus.RESOLVED]))
        .order_by(SortingItem.created_at.desc())
        .all()
    )


@router.post("/scan", status_code=202, response_model=JobQueuedOut)
def trigger_sorting_scan(library_id: int, _admin: User = Depends(require_admin)) -> dict[str, Any]:
    job = get_scan_queue().enqueue(sorting_scan_task, library_id, job_timeout="2h")
    return {"job_id": job.id}


@router.post("/apply", status_code=202, response_model=JobQueuedOut)
def trigger_sorting_apply(library_id: int, _admin: User = Depends(require_admin)) -> dict[str, Any]:
    job = get_scan_queue().enqueue(sorting_apply_task, library_id, job_timeout="2h")
    return {"job_id": job.id}


@router.post("/write-comicinfo", status_code=202, response_model=JobQueuedOut)
def trigger_write_comicinfo(library_id: int, _admin: User = Depends(require_admin)) -> dict[str, Any]:
    job = get_scan_queue().enqueue(write_comicinfo_task, library_id, job_timeout="2h")
    return {"job_id": job.id}


@router.post("/{item_id}/resolve", response_model=SortingItemOut)
def resolve_sorting_item(
    item_id: int, payload: SortingResolve, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> SortingItem:
    item = db.get(SortingItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Sorting item not found")
    if item.status == SortingStatus.APPLIED:
        raise HTTPException(status_code=409, detail="Already applied, can't change its type now")

    item.resolved_type = payload.resolved_type
    item.status = SortingStatus.RESOLVED
    item.resolved_at = dt.datetime.utcnow()
    item.apply_error = None
    db.commit()
    db.refresh(item)
    return item


@router.post("/{item_id}/skip", response_model=SortingItemOut)
def skip_sorting_item(
    item_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> SortingItem:
    item = db.get(SortingItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Sorting item not found")
    if item.status == SortingStatus.APPLIED:
        raise HTTPException(status_code=409, detail="Already applied, can't skip it now")

    item.status = SortingStatus.SKIPPED
    db.commit()
    db.refresh(item)
    return item
