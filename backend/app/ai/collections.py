"""AI-generated collections — an admin types a free-text theme and this
picks a subset of ALREADY-OWNED books that fit it, unlike
recommendations.py (which suggests books NOT owned). Same provider
dispatch, different prompt/response shape (app/ai/parsing.py's
parse_collection_selection) and a different grounding problem: instead of
excluding titles, the LLM is given a closed list of real library titles
to choose FROM, and its answer is fuzzy-matched back against that same
list (difflib — no new dependency for this) so a hallucinated title never
silently becomes an empty/wrong entry in the resulting collection.
"""

from __future__ import annotations

import difflib
import json
import logging

from sqlalchemy.orm import Session

from app.ai.base import AIProviderError, AISuggestion
from app.ai.dispatch import generate_text
from app.ai.parsing import parse_collection_selection
from app.config import Settings
from app.models.book import Book, visible_books
from app.models.collection import Collection
from app.models.enums import AIProvider, CollectionType
from app.models.metadata import BookMetadata

logger = logging.getLogger(__name__)

_LIBRARY_CONTEXT_LIMIT = 300
_SUMMARY_CHARS = 300
_MATCH_THRESHOLD = 0.72

_SYSTEM_PROMPT = (
    "Du hjälper till att bygga samlingar av redan ägda serier/böcker/manga i appen Kodex. "
    "Du får en bibliotekslista (JSON) och ett tema. Välj EXAKT de titlar ur listan som passar temat — "
    "rekommendera ALDRIG en titel som inte finns i listan. Föreslå också ett kort, passande svenskt "
    "samlingsnamn om inget namn redan är givet. "
    "Svara ENDAST med ett JSON-objekt på exakt denna form, ingen annan text:\n"
    '{"collection_name": str, "books": [{"title": str, "author": str, "reason": str}]}'
)


def build_library_context(
    db: Session, *, library_id: int | None = None, limit: int = _LIBRARY_CONTEXT_LIMIT
) -> list[dict]:
    """Each entry keeps its Book.id (`id`) for matching the LLM's answer
    back to a real row — stripped out before the list is sent to the LLM
    itself, see generate_collection_from_prompt's `prompt_items`. Capped
    at `limit`, most-recently-added first: a personal library (a few
    hundred books, per this app's own production scale) fits comfortably,
    but this is a known ceiling for a much larger one — worth revisiting
    if it ever becomes real for this deployment.
    """
    query = (
        db.query(Book.id, BookMetadata.title, BookMetadata.authors, BookMetadata.genres, BookMetadata.summary)
        .join(BookMetadata, BookMetadata.book_id == Book.id)
        .filter(visible_books())
    )
    if library_id is not None:
        query = query.filter(Book.library_id == library_id)
    rows = query.order_by(Book.added_at.desc()).limit(limit).all()
    return [
        {
            "id": book_id,
            "title": title,
            "author": ", ".join(authors) if authors else None,
            "genres": genres or [],
            "summary": (summary[:_SUMMARY_CHARS] if summary else None),
        }
        for book_id, title, authors, genres, summary in rows
    ]


def _match_book_id(suggestion: AISuggestion, context: list[dict]) -> int | None:
    target = suggestion.title.strip().lower()
    best_id: int | None = None
    best_score = 0.0
    for item in context:
        if not item["title"]:
            continue
        score = difflib.SequenceMatcher(None, target, item["title"].strip().lower()).ratio()
        if score > best_score:
            best_score, best_id = score, item["id"]
    return best_id if best_score >= _MATCH_THRESHOLD else None


def generate_collection_from_prompt(
    db: Session, *, prompt: str, settings: Settings, library_id: int | None = None, name_override: str | None = None
) -> Collection:
    if not settings.ai_provider or not settings.ai_api_key:
        raise AIProviderError("AI-samlingar är inte konfigurerat (ai_provider/ai_api_key saknas)")
    try:
        provider = AIProvider(settings.ai_provider)
    except ValueError as exc:
        raise AIProviderError(f"Okänd AI-provider: {settings.ai_provider}") from exc

    context = build_library_context(db, library_id=library_id)
    if not context:
        raise AIProviderError("Inga böcker i biblioteket att välja bland ännu")

    prompt_items = [{k: v for k, v in item.items() if k != "id"} for item in context]
    user_prompt = json.dumps({"tema": prompt, "bibliotek": prompt_items}, ensure_ascii=False)

    raw_text = generate_text(
        provider,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        api_key=settings.ai_api_key,
        model=settings.ai_model,
    )
    ai_name, suggestions = parse_collection_selection(raw_text)

    book_ids: list[int] = []
    for suggestion in suggestions:
        book_id = _match_book_id(suggestion, context)
        if book_id is not None and book_id not in book_ids:
            book_ids.append(book_id)
    if not book_ids:
        raise AIProviderError("AI:n hittade inga böcker i biblioteket som matchade temat")

    books_by_id = {book.id: book for book in db.query(Book).filter(Book.id.in_(book_ids)).all()}
    ordered_books = [books_by_id[book_id] for book_id in book_ids if book_id in books_by_id]

    collection = Collection(
        name=name_override or ai_name or f"AI: {prompt[:80]}", collection_type=CollectionType.MANUAL
    )
    collection.books = ordered_books
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection
