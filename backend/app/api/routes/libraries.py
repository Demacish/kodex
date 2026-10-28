from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin, require_admin_or_upload_key
from app.config import get_settings
from app.database import get_db
from app.models.library import Library
from app.scanning.series_json import import_library_series_json
from app.schemas.common import JobQueuedOut
from app.schemas.library import LibraryBrowseEntryOut, LibraryBrowseOut, LibraryCreate, LibraryOut, LibraryUpdate
from app.workers.queue import get_enrichment_queue, get_fulltext_queue, get_panel_queue, get_scan_queue
from app.workers.tasks import (
    detect_panels_library_task,
    enrich_library_task,
    fulltext_index_library_task,
    scan_library_task,
)

# B7 — admin manual file upload into a library folder. Only real,
# single-file book formats: IMAGE_FOLDER (a whole directory of loose
# images) isn't something a single browser upload can represent.
_UPLOAD_EXTENSIONS = {".cbz", ".cbr", ".cb7", ".epub", ".pdf"}
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024

router = APIRouter(prefix="/libraries", tags=["libraries"])


@router.get("", response_model=list[LibraryOut])
def list_libraries(db: Session = Depends(get_db), _user=Depends(get_current_user)) -> list[Library]:
    return db.query(Library).order_by(Library.name).all()


@router.get("/{library_id}", response_model=LibraryOut)
def get_library(library_id: int, db: Session = Depends(get_db), _user=Depends(get_current_user)) -> Library:
    library = db.get(Library, library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")
    return library


@router.post("", response_model=LibraryOut, status_code=201)
def create_library(payload: LibraryCreate, db: Session = Depends(get_db), _admin=Depends(require_admin)) -> Library:
    if db.query(Library).filter(Library.path == payload.path).one_or_none():
        raise HTTPException(status_code=409, detail="A library with this path already exists")

    library = Library(name=payload.name, path=payload.path, library_type=payload.library_type)
    db.add(library)
    db.commit()
    db.refresh(library)
    return library


@router.patch("/{library_id}", response_model=LibraryOut)
def update_library(
    library_id: int, payload: LibraryUpdate, db: Session = Depends(get_db), _admin=Depends(require_admin)
) -> Library:
    """Rename a library and/or change its type. A type change only affects
    future enrichment/merging decisions; existing metadata is left as is.
    """
    library = db.get(Library, library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    fields = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in fields:
        fields["name"] = fields["name"].strip()
        if not fields["name"]:
            raise HTTPException(status_code=422, detail="Name must not be blank")

    for key, value in fields.items():
        setattr(library, key, value)
    db.commit()
    db.refresh(library)
    return library


@router.post("/{library_id}/scan", status_code=202, response_model=JobQueuedOut)
def trigger_scan(library_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)) -> dict:
    """Enqueue a scan job for one library. Fulltext indexing is a separate,
    equally manual, per-library trigger — added in a later phase — kept
    apart from scanning on purpose (see the architecture plan).
    """
    library = db.get(Library, library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    # No timeout override here defaults to RQ's 180s job_timeout, which a
    # real library (hundreds of archives, some needing an unrar fallback
    # per file — see app/scanning/archive.py) blows through easily: RQ then
    # SIGKILLs the still-running work-horse ("Killed horse ... Work-horse
    # terminated unexpectedly") partway through, losing the whole scan
    # rather than just erroring the one file it was on. Seen in production
    # 2026-09-10 on a 380-book library.
    job = get_scan_queue().enqueue(scan_library_task, library.id, job_timeout="2h")
    return {"job_id": job.id}


def _resolve_within_library(library_root: Path, relative_path: str) -> Path:
    cleaned = relative_path.strip().strip("/")
    target = (library_root / cleaned).resolve() if cleaned else library_root
    if target != library_root and library_root not in target.parents:
        raise HTTPException(status_code=400, detail="path must stay inside the library")
    return target


@router.get("/{library_id}/browse", response_model=LibraryBrowseOut)
def browse_library(
    library_id: int, path: str = "", db: Session = Depends(get_db), _admin=Depends(require_admin)
) -> LibraryBrowseOut:
    """The admin-upload file browser's data source (ReadMeABook-inspired —
    see claude/omnibus-och-ai-forbattringar.md's "Övriga UX-idéer" note):
    lists a folder's subfolders (with a recursive importable-file count
    each, so an admin can tell "Absolute Corvid" already has 12 issues
    without opening it) and loose importable files, so LibraryFileUpload
    on the frontend can offer real navigation instead of a blind
    free-text subfolder field. Read-only — never creates or touches
    anything on disk, unlike POST .../upload below.
    """
    library = db.get(Library, library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    settings = get_settings()
    library_root = (settings.libraries_root / library.path).resolve()
    target_dir = _resolve_within_library(library_root, path)

    if not target_dir.is_dir():
        if target_dir == library_root:
            # Library folder doesn't exist on disk yet (e.g. a brand new
            # library before its first upload/scan) — an empty root is a
            # normal starting point, not an error.
            return LibraryBrowseOut(path="", breadcrumbs=[], entries=[])
        raise HTTPException(status_code=404, detail="Folder not found")

    entries = []
    for child in sorted(target_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.name.startswith("."):
            continue
        if child.is_dir():
            book_count = sum(1 for f in child.rglob("*") if f.is_file() and f.suffix.lower() in _UPLOAD_EXTENSIONS)
            entries.append(LibraryBrowseEntryOut(name=child.name, is_dir=True, book_count=book_count))
        elif child.suffix.lower() in _UPLOAD_EXTENSIONS:
            entries.append(LibraryBrowseEntryOut(name=child.name, is_dir=False))

    relative = target_dir.relative_to(library_root)
    normalized = "" if str(relative) == "." else str(relative)
    breadcrumbs = normalized.split("/") if normalized else []

    return LibraryBrowseOut(path=normalized, breadcrumbs=breadcrumbs, entries=entries)


@router.post("/{library_id}/upload", status_code=201)
async def upload_book_file(
    library_id: int,
    file: UploadFile,
    subfolder: str = Form(default=""),
    # False skips the scan this upload would otherwise queue — for a batch
    # (another Kodex server copying several volumes, see kodex/delivery/federation/peers.py) that
    # only wants one scan, after its last file.
    rescan: bool = Form(default=True),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin_or_upload_key),
) -> dict:
    """B7 — admin drops a single book file (CBZ/CBR/EPUB/PDF) straight
    into a library folder from the browser, then triggers the same scan
    job /scan already does — the manual-request-fulfillment counterpart to
    the request queue (see requests.py): approve a request, then land the
    file here instead of needing shell/file-manager access to the server.

    Also the landing point for a headless folder-watcher script on an
    external download-manager host (Mylar3/Kapowarr — see requests.py's
    send_to_mylar3/send_to_kapowarr and app/config.py's upload_api_key
    docstring): require_admin_or_upload_key accepts either a normal
    admin session (browser) or a shared X-Kodex-Upload-Key header
    (script), so this one endpoint serves both.

    `subfolder` (optional) is a relative path inside the library, e.g. a
    series folder name — resolved and checked to still be inside the
    library root before anything is written, so neither it nor the
    filename can escape via "..".
    """
    library = db.get(Library, library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")
    if library.read_only:
        raise HTTPException(status_code=409, detail="The library is read-only")

    filename = Path(file.filename or "").name  # strip any directory components the client sent
    extension = Path(filename).suffix.lower()
    if not filename or extension not in _UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {extension or '(none)'}. Use one of {sorted(_UPLOAD_EXTENSIONS)}.",
        )

    settings = get_settings()
    library_root = (settings.libraries_root / library.path).resolve()
    target_dir = _resolve_within_library(library_root, subfolder)
    # filename has no path separators (see Path(...).name above), so
    # target_dir/filename can't itself escape target_dir — no separate
    # check needed for the full target_path.
    target_path = target_dir / filename

    if target_path.exists():
        raise HTTPException(status_code=409, detail=f"{filename} already exists at that location")

    # Written to disk a megabyte at a time (never the whole file in memory:
    # a NAS has little), to a hidden partial file that becomes the book only
    # when it is complete and within the limit.
    partial = target_dir / f".{filename}.uploading"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        with partial.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > _MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=400,
                                        detail=f"File too large (max {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB)")  # fmt: skip
                out.write(chunk)
        partial.rename(target_path)
    except PermissionError as exc:
        raise HTTPException(
            status_code=409,
            detail="Kodex can't write to this library's folder: check the permissions of the mounted libraries",
        ) from exc
    finally:
        partial.unlink(missing_ok=True)

    if not rescan:
        return {"path": str(target_path.relative_to(library_root)), "job_id": None}
    job = get_scan_queue().enqueue(scan_library_task, library.id, job_timeout="2h")
    return {"path": str(target_path.relative_to(library_root)), "job_id": job.id}


@router.post("/{library_id}/import-series-json")
def import_series_json(library_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)) -> dict:
    """B9 — restores metadata from every series.json found under this
    library's folder (see app/scanning/series_json.py) onto Book rows a
    scan has already created. Run this after a rescan when recovering
    from a lost/corrupted database — see that module's own docstring for
    the full recovery story. Synchronous (not queued): this is JSON
    parsing + plain DB upserts, not archive decoding, so even a library
    with hundreds of series.json files finishes in well under RQ's
    default job timeout.
    """
    library = db.get(Library, library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    settings = get_settings()
    results = import_library_series_json(db, library, libraries_root=settings.libraries_root)
    return {
        "files_found": len(results),
        "books_updated": sum(r["updated"] for r in results),
        "books_not_found": sum(r["not_found"] for r in results),
        "results": results,
    }


@router.post("/{library_id}/enrich", status_code=202, response_model=JobQueuedOut)
def trigger_enrichment(
    library_id: int, force: bool = False, db: Session = Depends(get_db), _admin=Depends(require_admin)
) -> dict:
    """Enqueue an automatic metadata-enrichment pass for one library.

    Only touches books with thin metadata unless force=True is passed, and
    never touches a book whose metadata is already marked MANUAL (a
    previous manual match, or a future hand-edit) — see
    app/enrichment/engine.py. Books that still don't get a match after this
    can be fixed individually via /books/{id}/enrichment/search + /apply.
    """
    library = db.get(Library, library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    # Same "RQ's 180s default kills a long-running library-wide job" reason
    # as trigger_scan above, but needs much more headroom than the 2h used
    # elsewhere: enrichment makes ~2-4 rate-limited Comic Vine calls
    # (app/enrichment/ratelimit.py, 200/hour) per thin book, so a first
    # pass over a few hundred books can genuinely take several hours. The
    # limiter blocks/sleeps rather than failing, so this is just letting
    # it run — is_thin() gating already makes a killed/re-triggered run
    # resume where it left off rather than restart, but there's no reason
    # to force that when a longer timeout avoids it entirely.
    job = get_enrichment_queue().enqueue(enrich_library_task, library.id, force, job_timeout="12h")
    return {"job_id": job.id}


@router.post("/{library_id}/fulltext-index", status_code=202, response_model=JobQueuedOut)
def trigger_fulltext_index(library_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)) -> dict:
    """Enqueue a full-text extraction + indexing pass for one library.

    Manual and per-library on purpose (see the architecture plan): unlike
    metadata indexing, this is never run automatically on scan, since
    extracting the text of every EPUB chapter / PDF page in a library is
    far more expensive than reading its metadata. CBZ/CBR books have no
    text layer and are skipped. Sets Library.last_fulltext_indexed_at when
    the job completes.
    """
    library = db.get(Library, library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    # Same "RQ's 180s default kills a long-running library-wide job" reason
    # as trigger_scan above — this is the single most expensive per-library
    # job (extracts and indexes full text per book).
    job = get_fulltext_queue().enqueue(fulltext_index_library_task, library.id, job_timeout="2h")
    return {"job_id": job.id}


@router.post("/{library_id}/detect-panels", status_code=202, response_model=JobQueuedOut)
def trigger_panel_detection(
    library_id: int, force: bool = False, db: Session = Depends(get_db), _admin=Depends(require_admin)
) -> dict:
    """Enqueue a Guided View panel-detection pass for every page-based book
    in one library. Manual and per-library, same convention as /enrich and
    /fulltext-index above — no automatic scheduling on scan. See
    app.config.Settings.guided_view_enabled for the global kill switch;
    this endpoint stays enabled either way (it's a fast no-op per book when
    the flag is off) so there's nothing to remember to re-guard once it's
    turned back on.
    """
    library = db.get(Library, library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    # Same "RQ's 180s default kills a long-running library-wide job" reason
    # as trigger_scan/trigger_enrichment above — OpenCV panel detection runs
    # per page, so a few hundred books adds up.
    job = get_panel_queue().enqueue(detect_panels_library_task, library.id, force, job_timeout="4h")
    return {"job_id": job.id}
