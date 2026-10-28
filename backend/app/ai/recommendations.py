""" "För dig" / swipe-discovery recommendations — orchestrates
app/ai/dispatch.py against the current user's own library + suggestion
history and turns the result into cached AIRecommendation rows.

Grounding against hallucinated duplicates follows ReadMeABook's BookDate
feature (see the research this was modeled on): send the user's actual
library and prior suggestion/request titles as explicit "don't recommend
these" context in the prompt, then defensively re-filter the LLM's answer
against that same list rather than trusting the prompt instruction alone.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.ai.base import AIProviderError, AISuggestion
from app.ai.covers import fetch_cover_urls
from app.ai.dispatch import generate_text
from app.ai.parsing import parse_recommendations
from app.config import Settings
from app.models.ai_recommendation import AIRecommendation
from app.models.book import Book, visible_books
from app.models.enums import AIProvider, AISuggestionStatus, RequestMediaType
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.reading_progress import ReadingProgress
from app.models.request import Request
from app.models.user import User

logger = logging.getLogger(__name__)

_OWNED_LIBRARY_LIMIT = 50
_SUMMARY_CHARS = 400

_SYSTEM_PROMPT = (
    "Du är en expert på serier, manga och böcker som ger personliga rekommendationer i appen Kodex. "
    "Föreslå titlar personen INTE redan äger, baserat på deras bibliotek och tidigare svep/önskemål. "
    'Rekommendera ALDRIG något som förekommer i "ägs_redan" eller "redan_foreslaget_eller_begart". '
    "Svara ENDAST med ett JSON-objekt på exakt denna form, ingen annan text:\n"
    '{"recommendations": [{"title": str, "author": str, "reason": str, '
    '"media_type": "series" | "ebook" | "manga"}]}'
)


def _valid_media_type(raw: str | None) -> RequestMediaType | None:
    if raw is None:
        return None
    try:
        return RequestMediaType(raw)
    except ValueError:
        return None


def build_owned_context(db: Session, user: User) -> list[dict]:
    """Up to _OWNED_LIBRARY_LIMIT of the user's books, an even split across
    every library_type they actually own something in (each type's own
    share most-recently-added first) — NOT a flat "most recently added
    overall" query. That flat version was the original approach here,
    same cap-and-recency choice BookDate makes, but it has a real failure
    mode: a single big bulk import (e.g. onboarding a whole manga library
    at once) dominates "recently added" for weeks, crowding every other
    type out of the AI's context entirely regardless of how large that
    other type's library actually is — seen 2026-09-21 as recommendations
    turning 100% manga right after a manga import, even though comics
    outnumbered manga 253-to-38 overall. Splitting evenly per type keeps
    every owned type represented in proportion to the fixed budget, not
    to import timing.
    """
    library_types = [
        row[0]
        for row in (
            db.query(Library.library_type)
            .join(Book, Book.library_id == Library.id)
            .filter(visible_books())
            .distinct()
            .all()
        )
    ]
    if not library_types:
        return []
    per_type_limit = max(1, _OWNED_LIBRARY_LIMIT // len(library_types))

    rows = []
    for library_type in library_types:
        rows.extend(
            db.query(Book, BookMetadata, ReadingProgress)
            .join(BookMetadata, BookMetadata.book_id == Book.id)
            .join(Library, Library.id == Book.library_id)
            .outerjoin(ReadingProgress, (ReadingProgress.book_id == Book.id) & (ReadingProgress.user_id == user.id))
            .filter(Library.library_type == library_type, visible_books())
            .order_by(Book.added_at.desc())
            .limit(per_type_limit)
            .all()
        )

    context = []
    for _book, meta, progress in rows:
        if progress is not None and progress.is_finished:
            status = "läst"
        elif progress is not None and progress.progress_percent > 0:
            status = "pågående"
        else:
            status = "oläst"
        context.append(
            {
                "title": meta.title,
                "author": ", ".join(meta.authors) if meta.authors else None,
                "genres": meta.genres or [],
                "summary": (meta.summary[:_SUMMARY_CHARS] if meta.summary else None),
                "status": status,
            }
        )
    return context


def _already_seen_titles(db: Session, user: User) -> set[str]:
    """Titles that must never be re-suggested: anything this user has
    already been shown by AI (any status — a dismissal is still a "don't
    show again", see AISuggestionStatus.DISMISSED's docstring) plus
    anything they've already submitted as an ordinary Request (AI-sourced
    or not) — a manually-requested title showing back up as an AI
    "recommendation" would be a confusing, pointless repeat.
    """
    suggested = db.query(AIRecommendation.title).filter(AIRecommendation.user_id == user.id).all()
    requested = db.query(Request.title).filter(Request.requested_by_user_id == user.id).all()
    return {title.lower() for (title,) in [*suggested, *requested]}


def generate_recommendations_for_user(
    db: Session, user: User, settings: Settings, *, count: int = 20
) -> list[AIRecommendation]:
    if not settings.ai_provider or not settings.ai_api_key:
        raise AIProviderError("AI-rekommendationer är inte konfigurerat (ai_provider/ai_api_key saknas)")
    try:
        provider = AIProvider(settings.ai_provider)
    except ValueError as exc:
        raise AIProviderError(f"Okänd AI-provider: {settings.ai_provider}") from exc

    owned = build_owned_context(db, user)
    owned_titles = {item["title"].lower() for item in owned if item["title"]}
    seen_titles = _already_seen_titles(db, user)

    user_prompt = json.dumps(
        {
            "antal_onskade_forslag": count,
            "ägs_redan": owned,
            "redan_foreslaget_eller_begart": sorted(seen_titles - owned_titles),
        },
        ensure_ascii=False,
    )

    raw_text = generate_text(
        provider,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        api_key=settings.ai_api_key,
        model=settings.ai_model,
    )
    suggestions = parse_recommendations(raw_text)

    # Defensive re-filter — the prompt instructs the LLM not to repeat
    # owned/seen titles, but an LLM instruction is not a guarantee (see
    # this module's docstring).
    excluded = owned_titles | seen_titles
    fresh: list[AISuggestion] = []
    seen_this_batch: set[str] = set()
    for suggestion in suggestions:
        key = suggestion.title.lower()
        if key in excluded or key in seen_this_batch:
            continue
        seen_this_batch.add(key)
        fresh.append(suggestion)

    # Regenerating replaces the previous SUGGESTED batch (a fresh "Visa
    # fler" click shouldn't leave stale, already-superseded suggestions
    # lying around) but keeps REQUESTED/DISMISSED rows — those are real
    # history that _already_seen_titles above (and any future generation)
    # depends on.
    db.query(AIRecommendation).filter(
        AIRecommendation.user_id == user.id, AIRecommendation.status == AISuggestionStatus.SUGGESTED
    ).delete()

    cover_urls = fetch_cover_urls(
        [(suggestion.title, _valid_media_type(suggestion.media_type_guess)) for suggestion in fresh],
        comicvine_api_key=settings.comicvine_api_key,
        google_books_api_key=settings.google_books_api_key,
    )
    rows = [
        AIRecommendation(
            user_id=user.id,
            title=suggestion.title,
            author=suggestion.author,
            reason=suggestion.reason,
            media_type_guess=_valid_media_type(suggestion.media_type_guess),
            cover_url=cover_url,
            status=AISuggestionStatus.SUGGESTED,
        )
        for suggestion, cover_url in zip(fresh, cover_urls, strict=True)
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows
