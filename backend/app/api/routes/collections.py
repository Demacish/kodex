"""Manual and smart collections (see the architecture plan's "Modul: Smarta
samlingar"). A manual collection is just a curated list of books. A smart
collection has no book rows of its own — kodex/collections/rules.py compiles
its `rule` into a Meilisearch filter, evaluated fresh against the books
index every time its contents are requested, so it always reflects the
current library (e.g. "everything tagged Pirates" picks up new books on
the next view, with no re-curation needed).

Creating, editing and deleting collections is an admin action, matching
how library management works elsewhere in this API; there's no admin UI
for it yet (same "usable via the API today, a UI comes in a later phase"
state library creation is in — see the home page's own note about that).
Viewing collections and their resolved books is open to any logged-in
reader.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ai.base import AIProviderError
from app.ai.collections import generate_collection_from_prompt
from app.auth import get_current_user, require_admin
from app.config import get_settings
from app.database import get_db
from app.enrichment.story_arc_roster import fetch_arc_name
from app.models.book import Book, visible_books
from app.models.collection import Collection, collection_books
from app.models.enums import CollectionType, RequestMediaType, RequestStatus
from app.models.request import Request
from app.models.story_arc import StoryArc, StoryArcIssue
from app.models.user import User
from app.schemas.ai import AICollectionGenerateIn
from app.schemas.book import BookOut
from app.schemas.collection import CollectionCreate, CollectionOut, CollectionUpdate
from app.schemas.common import JobQueuedOut
from app.schemas.csv_import import CsvImportConfirmIn, CsvImportPreviewOut
from app.schemas.story_arc import StoryArcImportIn, StoryArcImportOut, StoryArcOut
from app.workers.queue import get_enrichment_queue
from app.workers.tasks import refresh_story_arc_task
from kodex.collections import cbl, members
from kodex.collections.csv_import import CsvImportError, match_rows, parse_csv
from kodex.collections.rules import RuleError, validate
from kodex.delivery.notify import notify_bulk_requests

router = APIRouter(prefix="/collections", tags=["collections"])


def _get_collection_or_404(collection_id: int, db: Session) -> Collection:
    collection = db.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


def _manual_book_positions(collection_id: int, db: Session) -> dict[int, int]:
    """book_id -> position for a manual collection's association rows —
    NULL until PUT /collections/{id}/order has been called at least once
    (see collection_books' own docstring on the column).
    """
    rows = db.execute(
        select(collection_books.c.book_id, collection_books.c.position).where(
            collection_books.c.collection_id == collection_id
        )
    ).all()
    return {book_id: position for book_id, position in rows if position is not None}


def _manual_sort_key(book: Book, positions: dict[int, int]) -> tuple:
    """A book with an explicit position (set via a reorder) always sorts
    before one without, in position order; anything never explicitly
    ordered keeps falling back to the original number/file_path
    heuristic, so a collection nobody has reordered yet behaves exactly
    as before this feature existed.
    """
    position = positions.get(book.id)
    if position is not None:
        return (0, position)
    return (1, book.number is None, book.number or 0, book.file_path)


def _resolve_book_ids(collection: Collection, db: Session, user_id: int | None = None) -> list[int]:
    """The ordered book ids a collection resolves to for this user
    (kodex.collections.members), the same order get_collection_books uses."""
    return members.book_ids(db, collection, user_id)


def _visible(books: list[Book]) -> list[Book]:
    """A manual collection's books minus the ones hidden because their
    file is missing (Book.missing_since) — they stay members, just aren't
    shown or counted until they're back."""
    return [b for b in books if b.missing_since is None]


@router.get("", response_model=list[CollectionOut])
def list_collections(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CollectionOut]:
    """Powers the card-grid Collections page (2026-09-11, modeled after
    metron.cloud/reading-lists/) — each card needs a cover + book count,
    computed here rather than left to the frontend so a smart collection
    (no book rows of its own) works the same as a manual one. One query
    per smart collection, for this user — see _resolve_book_ids.
    """
    collections = (
        db.query(Collection)
        .filter(or_(Collection.owner_user_id.is_(None), Collection.owner_user_id == user.id))
        .order_by(Collection.name)
        .all()
    )
    story_arc_by_collection_id = {
        story_arc.collection_id: story_arc.id
        for story_arc in db.query(StoryArc.id, StoryArc.collection_id).filter(StoryArc.collection_id.isnot(None))
    }

    out = []
    for collection in collections:
        book_ids = _resolve_book_ids(collection, db, user.id)
        out.append(
            CollectionOut(
                id=collection.id,
                name=collection.name,
                collection_type=collection.collection_type,
                rule=collection.rule,
                owner_user_id=collection.owner_user_id,
                book_count=len(book_ids),
                cover_book_id=book_ids[0] if book_ids else None,
                has_custom_cover=collection.cover_image_path is not None,
                story_arc_id=story_arc_by_collection_id.get(collection.id),
            )
        )
    return out


@router.post("", response_model=CollectionOut, status_code=201)
def create_collection(
    payload: CollectionCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> Collection:
    if payload.collection_type == CollectionType.SMART:
        try:
            validate(payload.rule)  # validated up front — see rules.py
        except RuleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    collection = Collection(
        name=payload.name,
        collection_type=payload.collection_type,
        rule=payload.rule,
        owner_user_id=admin.id if payload.personal else None,
    )

    if payload.collection_type == CollectionType.MANUAL and payload.book_ids:
        books = db.query(Book).filter(Book.id.in_(payload.book_ids)).all()
        found_ids = {b.id for b in books}
        missing = set(payload.book_ids) - found_ids
        if missing:
            raise HTTPException(status_code=404, detail=f"Unknown book id(s): {sorted(missing)}")
        collection.books = books

    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


@router.post("/generate", response_model=CollectionOut, status_code=201)
def generate_collection(
    payload: AICollectionGenerateIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> CollectionOut:
    """AI-generated collection (see app/ai/collections.py) — an admin
    types a free-text theme, the configured LLM picks matching titles out
    of the ALREADY-OWNED library (never something to acquire — that's
    app/ai/recommendations.py's "För dig" feed instead, see
    api/routes/ai.py), and this creates a normal manual Collection from
    the result. Admin-only, same as every other collection-management
    endpoint on this router.
    """
    settings = get_settings()
    if not settings.ai_provider or not settings.ai_api_key:
        raise HTTPException(status_code=400, detail="AI-samlingar är inte konfigurerat än")
    try:
        collection = generate_collection_from_prompt(
            db, prompt=payload.prompt, settings=settings, library_id=payload.library_id, name_override=payload.name
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return CollectionOut(
        id=collection.id,
        name=collection.name,
        collection_type=collection.collection_type,
        rule=collection.rule,
        owner_user_id=collection.owner_user_id,
        book_count=len(collection.books),
        cover_book_id=collection.books[0].id if collection.books else None,
        has_custom_cover=False,
        story_arc_id=None,
    )


class CblEntryOut(BaseModel):
    series: str
    number: str | None
    volume: str | None
    year: str | None


class CblImportOut(BaseModel):
    collection: CollectionOut
    matched: int
    missing: list[CblEntryOut]


@router.post("/import-cbl", response_model=CblImportOut, status_code=201)
async def import_cbl(file: UploadFile, name: str | None = Form(default=None, max_length=255),
                     db: Session = Depends(get_db), user: User = Depends(require_admin)) -> CblImportOut:  # fmt: skip
    """A reading list (.cbl) as a manual collection of the listed books
    that are here, in the list's order; the rest come back as missing."""
    try:
        found = cbl.import_(db, await file.read(cbl.MAX_BYTES + 1), name=name or None)
    except cbl.CblError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    collection = found.collection
    ids = members.book_ids(db, collection, user.id)
    out = CollectionOut(id=collection.id, name=collection.name, collection_type=collection.collection_type,
                        rule=collection.rule, owner_user_id=collection.owner_user_id, book_count=len(ids),
                        cover_book_id=ids[0] if ids else None, has_custom_cover=False, story_arc_id=None)  # fmt: skip
    missing = [CblEntryOut(series=e.series, number=e.number, volume=e.volume, year=e.year) for e in found.missing]
    return CblImportOut(collection=out, matched=found.matched, missing=missing)


@router.post("/import-csv/preview", response_model=CsvImportPreviewOut)
async def preview_csv_import(
    file: UploadFile, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    """C14 — first step of importing a League of Comic Geeks or Goodreads
    export (see kodex/collections/csv_import.py): parses + fuzzy-matches every
    row against the local library, but creates nothing yet. Nothing
    questionable lands in a collection automatically — the caller reviews
    `needs_review`/`unmatched` and picks which book_ids to actually keep
    before calling /import-csv/confirm.
    """
    content = await file.read()
    try:
        rows = parse_csv(content)
    except CsvImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    matched_rows = match_rows(db, rows)
    return {
        "matched": [r for r in matched_rows if r.bucket == "matched"],
        "needs_review": [r for r in matched_rows if r.bucket == "needs_review"],
        "unmatched": [r for r in matched_rows if r.bucket == "unmatched"],
    }


@router.post("/import-csv/confirm", response_model=CollectionOut, status_code=201)
def confirm_csv_import(
    payload: CsvImportConfirmIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> CollectionOut:
    """Second step — creates a normal manual Collection from exactly the
    book_ids the caller accepted out of the preview (see
    preview_csv_import above), same shape as any other manual collection.
    """
    if not payload.book_ids:
        raise HTTPException(status_code=400, detail="No book_ids given")
    books = db.query(Book).filter(Book.id.in_(payload.book_ids)).all()
    found_ids = {b.id for b in books}
    missing = set(payload.book_ids) - found_ids
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown book id(s): {sorted(missing)}")

    # Preserve the order the caller sent, not whatever order the DB query
    # happened to return — same ordering guarantee as create_collection's
    # own book_ids handling.
    books_by_id = {b.id: b for b in books}
    ordered_books = [books_by_id[book_id] for book_id in payload.book_ids]

    collection = Collection(name=payload.name, collection_type=CollectionType.MANUAL)
    collection.books = ordered_books
    db.add(collection)
    db.commit()
    db.refresh(collection)

    return CollectionOut(
        id=collection.id,
        name=collection.name,
        collection_type=collection.collection_type,
        rule=collection.rule,
        owner_user_id=collection.owner_user_id,
        book_count=len(ordered_books),
        cover_book_id=ordered_books[0].id if ordered_books else None,
        has_custom_cover=False,
        story_arc_id=None,
    )


@router.post("/story-arc-import", response_model=StoryArcImportOut, status_code=202)
def build_story_arc_collection(
    payload: StoryArcImportIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    """C15 — an admin types (or pastes) a bare Comic Vine story-arc id to
    start tracking a whole crossover/event from scratch, before owning a
    single issue from it. Distinct from engine.py's _ensure_arc_collections,
    which only ever auto-creates an arc's smart Collection reactively, the
    first time an already-owned book happens to match it — this is the
    same shape built proactively instead, then reuses the exact on-demand
    roster-fetch job (refresh_story_arc_task) the "Uppdatera
    platshållare"-button above already triggers. No separate placeholder
    table/logic needed for the official reading order: StoryArcIssue rows
    with book_id IS NULL already are the "Saknas" placeholders (Uppdrag 7
    Del D).
    """
    settings = get_settings()
    if not settings.comicvine_api_key:
        raise HTTPException(status_code=400, detail="COMICVINE_API_KEY is not configured")

    existing = db.query(StoryArc).filter(StoryArc.comicvine_id == payload.comicvine_story_arc_id).one_or_none()
    if existing is not None and existing.collection_id is not None:
        # Already tracked — re-trigger a refresh instead of creating a duplicate collection.
        job = get_enrichment_queue().enqueue(refresh_story_arc_task, existing.id, job_timeout="10m")
        return {"collection_id": existing.collection_id, "job_id": job.id}

    arc_name = payload.name or fetch_arc_name(payload.comicvine_story_arc_id, settings.comicvine_api_key)
    if not arc_name:
        raise HTTPException(
            status_code=502, detail="Could not fetch this story arc's name from Comic Vine — give a name explicitly"
        )

    # Same idempotent name+rule lookup as _ensure_arc_collections, in case
    # a same-named smart collection already exists (hand-created, or
    # auto-created from an owned book tagged with this arc before anyone
    # tried this endpoint).
    collection = (
        db.query(Collection)
        .filter(Collection.name == arc_name, Collection.collection_type == CollectionType.SMART)
        .filter(Collection.rule.op("->>")("value") == arc_name)
        .one_or_none()
    )
    if collection is None:
        rule = {"field": "story_arcs", "value": arc_name}
        collection = Collection(name=arc_name, collection_type=CollectionType.SMART, rule=rule, owner_user_id=None)
        db.add(collection)
        db.flush()

    if existing is not None:
        existing.collection_id = collection.id
        db.add(existing)
        story_arc_id = existing.id
    else:
        story_arc = StoryArc(name=arc_name, collection_id=collection.id, comicvine_id=payload.comicvine_story_arc_id)
        db.add(story_arc)
        db.flush()
        story_arc_id = story_arc.id

    db.commit()

    job = get_enrichment_queue().enqueue(refresh_story_arc_task, story_arc_id, job_timeout="10m")
    return {"collection_id": collection.id, "job_id": job.id}


@router.get("/{collection_id}", response_model=CollectionOut)
def get_collection(
    collection_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CollectionOut:
    collection = _get_collection_or_404(collection_id, db)
    book_ids = _resolve_book_ids(collection, db, user.id)
    story_arc = db.query(StoryArc.id).filter(StoryArc.collection_id == collection.id).scalar()
    return CollectionOut(
        id=collection.id,
        name=collection.name,
        collection_type=collection.collection_type,
        rule=collection.rule,
        owner_user_id=collection.owner_user_id,
        book_count=len(book_ids),
        cover_book_id=book_ids[0] if book_ids else None,
        has_custom_cover=collection.cover_image_path is not None,
        story_arc_id=story_arc,
    )


@router.put("/{collection_id}", response_model=CollectionOut)
def update_collection(
    collection_id: int,
    payload: CollectionUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> Collection:
    collection = _get_collection_or_404(collection_id, db)

    if payload.name is not None:
        collection.name = payload.name

    if payload.rule is not None:
        if collection.collection_type != CollectionType.SMART:
            raise HTTPException(status_code=400, detail="Only smart collections have a rule")
        try:
            validate(payload.rule)
        except RuleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        collection.rule = payload.rule

    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


@router.delete("/{collection_id}", status_code=204, response_model=None)
def delete_collection(collection_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> None:
    collection = _get_collection_or_404(collection_id, db)
    db.delete(collection)
    db.commit()


@router.get("/{collection_id}/books", response_model=list[BookOut])
def get_collection_books(
    collection_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Book]:
    """The books in order: a manual collection's own, or what a smart
    collection's rule matches for this user (kodex.collections.members)."""
    collection = _get_collection_or_404(collection_id, db)
    ordered_ids = _resolve_book_ids(collection, db, user.id)
    if not ordered_ids:
        return []
    books_by_id = {b.id: b for b in db.query(Book).filter(Book.id.in_(ordered_ids), visible_books()).all()}
    return [books_by_id[book_id] for book_id in ordered_ids if book_id in books_by_id]


@router.get("/{collection_id}/cbl", response_class=Response, responses={200: {"content": {"application/xml": {}}}})
def export_cbl(collection_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    """The collection as a reading list (.cbl), in its order."""
    collection = _get_collection_or_404(collection_id, db)
    filename = "".join(c for c in collection.name if c.isascii() and (c.isalnum() or c in " -_")).strip() or "lista"
    return Response(cbl.export(db, collection, user.id), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{filename}.cbl"'})  # fmt: skip


@router.put("/{collection_id}/order", status_code=204, response_model=None)
def reorder_collection_books(
    collection_id: int,
    book_ids: list[int],
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """Sets an explicit reading order for a manual collection (E) —
    `book_ids` in the exact order they should appear in from now on.
    Only meaningful for manual collections: a smart collection's contents
    (and order) are computed fresh from `rule` every time, there's no
    per-book row to attach a position to. Must be the collection's full
    current book set, not a subset — a partial list would silently leave
    the missing books' old positions in place, mixed in with the new
    ones in a way nobody asked for.
    """
    collection = _get_collection_or_404(collection_id, db)
    if collection.collection_type != CollectionType.MANUAL:
        raise HTTPException(status_code=400, detail="Only manual collections can be reordered")

    # Books hidden because their file is missing aren't shown, so the
    # client can't order them: it sends the visible books, and the hidden
    # ones keep their relative order after them, ready for when they're
    # back.
    positions = _manual_book_positions(collection.id, db)
    current_ids = {b.id for b in _visible(collection.books)}
    if set(book_ids) != current_ids or len(book_ids) != len(current_ids):
        raise HTTPException(
            status_code=400,
            detail="book_ids must be exactly this collection's current books, each listed once",
        )
    hidden_ids = [
        b.id
        for b in sorted(collection.books, key=lambda b: _manual_sort_key(b, positions))
        if b.missing_since is not None
    ]

    for position, book_id in enumerate([*book_ids, *hidden_ids]):
        db.execute(
            collection_books.update()
            .where(collection_books.c.collection_id == collection_id, collection_books.c.book_id == book_id)
            .values(position=position)
        )
    db.commit()


@router.post("/{collection_id}/books", status_code=204, response_model=None)
def add_books_to_collection(
    collection_id: int,
    book_ids: list[int],
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    collection = _get_collection_or_404(collection_id, db)
    if collection.collection_type != CollectionType.MANUAL:
        raise HTTPException(status_code=400, detail="Only manual collections can have books added directly")

    books = db.query(Book).filter(Book.id.in_(book_ids)).all()
    found_ids = {b.id for b in books}
    missing = set(book_ids) - found_ids
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown book id(s): {sorted(missing)}")

    existing_ids = {b.id for b in collection.books}
    collection.books.extend(b for b in books if b.id not in existing_ids)
    db.add(collection)
    db.commit()


@router.delete("/{collection_id}/books", status_code=204, response_model=None)
def remove_books_from_collection(
    collection_id: int,
    book_ids: list[int],
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """Bulk counterpart to remove_book_from_collection below — symmetric
    with add_books_to_collection's bulk-add shape, for a multi-select
    "Ta bort ur samlingen" action (see BulkActionBar.tsx).
    """
    collection = _get_collection_or_404(collection_id, db)
    if collection.collection_type != CollectionType.MANUAL:
        raise HTTPException(status_code=400, detail="Only manual collections can have books removed directly")

    remove_ids = set(book_ids)
    collection.books = [b for b in collection.books if b.id not in remove_ids]
    db.add(collection)
    db.commit()


@router.delete("/{collection_id}/books/{book_id}", status_code=204, response_model=None)
def remove_book_from_collection(
    collection_id: int,
    book_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    collection = _get_collection_or_404(collection_id, db)
    if collection.collection_type != CollectionType.MANUAL:
        raise HTTPException(status_code=400, detail="Only manual collections can have books removed directly")

    collection.books = [b for b in collection.books if b.id != book_id]
    db.add(collection)
    db.commit()


_COVER_CONTENT_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_MAX_COVER_BYTES = 10 * 1024 * 1024


@router.post("/{collection_id}/cover", status_code=204, response_model=None)
async def upload_collection_cover(
    collection_id: int,
    file: UploadFile,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """Manual cover for a collection (D) — takes priority over the
    auto-computed "first book's cover" (see list_collections). Stored the
    same way BookMetadata.cover_path already is (relative path under
    settings.covers_dir), just in its own "collections" subfolder so a
    collection id and a book id can never collide on the same filename.
    """
    collection = _get_collection_or_404(collection_id, db)

    extension = _COVER_CONTENT_TYPES.get(file.content_type or "")
    if extension is None:
        raise HTTPException(
            status_code=400, detail=f"Unsupported image type: {file.content_type}. Use JPEG, PNG or WebP."
        )

    content = await file.read(_MAX_COVER_BYTES + 1)
    if len(content) > _MAX_COVER_BYTES:
        raise HTTPException(status_code=400, detail="Image too large (max 10MB)")

    settings = get_settings()
    covers_subdir = settings.covers_dir / "collections"
    covers_subdir.mkdir(parents=True, exist_ok=True)

    # Remove a previous cover in a different format first, so switching
    # from a .png to a .jpg doesn't leave the old file behind forever.
    if collection.cover_image_path:
        old_path = settings.covers_dir / collection.cover_image_path
        old_path.unlink(missing_ok=True)

    relative_path = f"collections/{collection_id}{extension}"
    (settings.covers_dir / relative_path).write_bytes(content)

    collection.cover_image_path = relative_path
    db.add(collection)
    db.commit()


@router.delete("/{collection_id}/cover", status_code=204, response_model=None)
def delete_collection_cover(
    collection_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> None:
    """Reverts a collection to its auto-computed cover."""
    collection = _get_collection_or_404(collection_id, db)
    if collection.cover_image_path:
        settings = get_settings()
        (settings.covers_dir / collection.cover_image_path).unlink(missing_ok=True)
        collection.cover_image_path = None
        db.add(collection)
        db.commit()


@router.get("/{collection_id}/cover")
def get_collection_cover(
    collection_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> FileResponse:
    collection = _get_collection_or_404(collection_id, db)
    if not collection.cover_image_path:
        raise HTTPException(status_code=404, detail="This collection has no custom cover")

    settings = get_settings()
    cover_path = settings.covers_dir / collection.cover_image_path
    if not cover_path.is_file():
        raise HTTPException(status_code=404, detail="This collection has no custom cover")
    return FileResponse(cover_path)


def _get_story_arc_or_404(collection_id: int, db: Session) -> StoryArc:
    """A story arc's full Comic Vine roster (Uppdrag 7 Del D) — distinct
    from the collection's own book list above, which is just "what we
    already own" via the smart-collection rule. Looked up by
    collection_id (not its own id) since the frontend only ever has the
    Collection it's already looking at, not a separate story-arc id.
    """
    story_arc = db.query(StoryArc).filter(StoryArc.collection_id == collection_id).one_or_none()
    if story_arc is None:
        raise HTTPException(
            status_code=404,
            detail="No Comic Vine story arc is linked to this collection (only auto-created arc collections have one)",
        )
    return story_arc


@router.get("/{collection_id}/story-arc", response_model=StoryArcOut)
def get_story_arc(
    collection_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> StoryArc:
    return _get_story_arc_or_404(collection_id, db)


@router.post("/{collection_id}/story-arc/refresh", status_code=202, response_model=JobQueuedOut)
def trigger_story_arc_refresh(
    collection_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    """Enqueues a fetch of this arc's full issue roster from Comic Vine —
    see app/workers/tasks.py's refresh_story_arc_task and
    app/enrichment/story_arc_roster.py for what that actually does (one
    API call for the roster + batched calls for issue details). Admin-
    only and on-demand rather than automatic: fetching a roster the first
    time a book from that arc matches would mean doing it dozens of times
    over for a big library-wide enrichment run before anyone's actually
    asked to see the "what's missing" view for that specific arc.
    """
    story_arc = _get_story_arc_or_404(collection_id, db)
    job = get_enrichment_queue().enqueue(refresh_story_arc_task, story_arc.id, job_timeout="10m")
    return {"job_id": job.id}


@router.post("/{collection_id}/request-missing", status_code=201)
def request_missing_issues(
    collection_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """ "Begär saknade nummer" — the bulk counterpart to StoryArcPanel.tsx's
    per-issue "Skapa önskemål" button, requested 2026-09-11 so requesting
    an entire arc's gap (or whatever's left of it) doesn't mean clicking
    through each placeholder one at a time. Creates one Request per
    currently-missing StoryArcIssue, all tagged with this collection_id
    (see Request.collection_id) so the admin queue can group/export them
    together. Skips an issue that already has a non-rejected request with
    the same title in this collection, so re-clicking after a partial
    fetch (or just clicking twice) doesn't pile up duplicates.
    """
    story_arc = _get_story_arc_or_404(collection_id, db)
    missing = (
        db.query(StoryArcIssue)
        .filter(StoryArcIssue.story_arc_id == story_arc.id, StoryArcIssue.book_id.is_(None))
        .all()
    )
    if not missing:
        return {"created": 0, "skipped": 0}

    already_requested = {
        title
        for (title,) in db.query(Request.title)
        .filter(Request.collection_id == collection_id, Request.status != RequestStatus.REJECTED)
        .all()
    }

    created = 0
    for issue in missing:
        if issue.display_name in already_requested:
            continue
        db.add(
            Request(
                requested_by_user_id=user.id,
                title=issue.display_name,
                media_type=RequestMediaType.SERIES,
                external_link=issue.site_detail_url,
                collection_id=collection_id,
            )
        )
        created += 1

    db.commit()

    if created:
        notify_bulk_requests(created, story_arc.name, settings=get_settings())

    return {"created": created, "skipped": len(missing) - created}
