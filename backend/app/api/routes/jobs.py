"""Background job status: one job by id (polled after starting a scan or
an enrichment) and the live list behind the admin job view. Jobs live in
PostgreSQL (kodex.jobs); a task's arguments are named, so a label like
"Skanning: Serier" is read from them.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models.book import Book
from app.models.library import Library
from app.models.story_arc import StoryArc
from app.workers.queue import fetch_job
from kodex.jobs import JobInfo
from kodex.jobs import list_jobs as _list_jobs


class JobOut(BaseModel):
    id: str
    queue: str
    # The task (scan_library_task, …) and what it works on, for clients
    # that word it themselves; label is v1's Swedish description.
    kind: str
    subject: str | None = None
    label: str
    status: str  # queued | started | finished | failed | canceled
    enqueued_at: dt.datetime | None = None
    started_at: dt.datetime | None = None
    ended_at: dt.datetime | None = None
    error: str | None = None


class JobStatusOut(BaseModel):
    id: str
    status: str
    result: Any = None


router = APIRouter(prefix="/jobs", tags=["jobs"])

# Maps a task's name to a label, by the kind of resource its arguments name
# ("Skanning: Serier" instead of a bare job id, the point of the list view).
_LIBRARY_SCOPED_TASKS = {
    "scan_library_task": "Skanning",
    "enrich_library_task": "Berikning",
    "fulltext_index_library_task": "Fulltextindexering",
    "sorting_scan_task": "Sorteringsanalys",
    "sorting_apply_task": "Verkställer sortering",
    "write_comicinfo_task": "Skriver ComicInfo.xml",
    "match_library_task": "Matchning",
    "generate_covers_task": "Omslag",
    "write_back_library_task": "Skriver metadata till filerna",
}
_BOOK_SCOPED_TASKS = {
    "enrich_book_task": "Berikning",
    "send_to_kindle_task": "Skicka till Kindle",
    "compute_page_dimensions_task": "Läser sidmått",
    "push_progress_upstream_task": "Synkar läsframsteg",
    "convert_book_task": "Konverterar till CBZ",
}
_GLOBAL_TASKS = {
    "check_followed_series_task": "Kolla nya utgåvor (följda serier)",
    "poll_libraries": "Letar efter ändrade bibliotek",
    "periodic_release_check": "Schemalägger koll av nya utgåvor",
    "remove_old_jobs": "Rensar gamla jobb",
}
_STORY_ARC_SCOPED_TASKS = {
    "refresh_story_arc_task": "Hämtar story arc-lista",
}


def _describe_job(job: JobInfo, db: Session) -> dict[str, Any]:
    name, args = job.task_name, job.args
    library_id = args.get("library_id", args.get("intake_library_id"))
    if name in _LIBRARY_SCOPED_TASKS and library_id is not None:
        library = db.get(Library, library_id)
        label = f"{_LIBRARY_SCOPED_TASKS[name]}: {library.name if library else f'bibliotek #{library_id}'}"
    elif name in _BOOK_SCOPED_TASKS and args.get("book_id") is not None:
        book = db.get(Book, args["book_id"])
        title = book.book_metadata.title if book and book.book_metadata else None
        label = f"{_BOOK_SCOPED_TASKS[name]}: {title or f'bok #{args["book_id"]}'}"
    elif name in _GLOBAL_TASKS:
        label = _GLOBAL_TASKS[name]
    elif name == "copy_books_to_peer_task":
        label = f"Kopierar {len(args.get('book_ids') or [])} böcker till {args.get('peer_name')}"
    elif name in _STORY_ARC_SCOPED_TASKS and args.get("story_arc_id") is not None:
        story_arc = db.get(StoryArc, args["story_arc_id"])
        label = f"{_STORY_ARC_SCOPED_TASKS[name]}: {story_arc.name if story_arc else f'arc #{args["story_arc_id"]}'}"
    else:
        label = name
    # Only the exception's message: a status list has no room for more.
    error = job.error.strip().splitlines()[-1] if job.error else None
    subject = None
    if name in _LIBRARY_SCOPED_TASKS and library_id is not None:
        subject = label.split(": ", 1)[-1]
    elif name in _BOOK_SCOPED_TASKS or name in _STORY_ARC_SCOPED_TASKS:
        subject = label.split(": ", 1)[-1] if ": " in label else None
    return {
        "id": job.id,
        "queue": job.queue,
        "kind": name,
        "subject": subject,
        "label": label,
        "status": job.status,
        "enqueued_at": job.enqueued_at,
        "started_at": job.started_at,
        "ended_at": job.ended_at,
        "error": error,
    }


@router.get("", response_model=list[JobOut])
def list_jobs(_admin=Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    """Every job queued or running, and those that ended in the last day,
    newest first. Polled by the admin job view (JobsPanel.tsx)."""
    return [_describe_job(job, db) for job in _list_jobs()]


@router.get("/{job_id}", response_model=JobStatusOut)
def get_job_status(job_id: str, _admin=Depends(require_admin)) -> dict:
    job = fetch_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"id": job.id, "status": job.status, "result": job.result}
