"""Tests for app/ai/recommendations.py — building the owned-library/
seen-titles context, generating a batch (with a monkeypatched
dispatch.generate_text so no real network call happens), and the
dedup/regenerate-replaces-SUGGESTED-only behavior.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import sessionmaker

import app.ai.recommendations as recommendations_module
from app.ai.base import AIProviderError
from app.ai.recommendations import build_owned_context, generate_recommendations_for_user
from app.config import Settings
from app.models.ai_recommendation import AIRecommendation
from app.models.book import Book
from app.models.enums import AISuggestionStatus, BookFormat, LibraryType, RequestMediaType
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.reading_progress import ReadingProgress
from app.models.request import Request
from app.models.user import User
from tests.db import fresh_engine


@pytest.fixture
def db():
    engine = fresh_engine()
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _no_real_cover_lookups(monkeypatch):
    """fetch_cover_urls hits real provider APIs (Comic Vine/AniList/Open
    Library/Google Books, see app/ai/covers.py) — none of that belongs in
    this file's tests, which are about the recommendation-generation
    logic, not cover lookups (those get their own tests in
    test_ai_covers.py). Autouse so every test in this file gets it
    without repeating the same monkeypatch line everywhere.
    """
    monkeypatch.setattr(recommendations_module, "fetch_cover_urls", lambda suggestions, **kw: [None] * len(suggestions))


def _make_user(db, *, username: str = "reader") -> User:
    user = User(oidc_subject=f"sub-{username}", username=username, is_admin=False)
    db.add(user)
    db.flush()
    return user


def _add_book(db, *, title: str, authors=None, genres=None, summary=None, finished=False, user=None) -> Book:
    library = db.query(Library).first()
    if library is None:
        library = Library(name="Lib", path="lib", library_type=LibraryType.COMICS)
        db.add(library)
        db.flush()
    book = Book(
        library_id=library.id, file_path=f"{title}.cbz", file_format=BookFormat.CBZ, file_size=1, file_mtime=0.0
    )
    db.add(book)
    db.flush()
    db.add(
        BookMetadata(
            book_id=book.id, title=title, sort_title=title, authors=authors or [], genres=genres or [], summary=summary
        )
    )
    if user is not None:
        db.add(
            ReadingProgress(
                user_id=user.id,
                book_id=book.id,
                position="1",
                progress_percent=100 if finished else 0,
                is_finished=finished,
            )
        )
    db.commit()
    return book


def _settings(**overrides) -> Settings:
    defaults = dict(database_url="sqlite:///:memory:", ai_provider="openai", ai_api_key="sk-test")
    defaults.update(overrides)
    return Settings(**defaults)


def test_build_owned_context_reports_finished_status(db):
    user = _make_user(db)
    _add_book(
        db,
        title="Bramble",
        authors=["Kentaro Miura"],
        genres=["Dark Fantasy"],
        summary="A cursed swordsman.",
        finished=True,
        user=user,
    )

    context = build_owned_context(db, user)

    assert context[0]["title"] == "Bramble"
    assert context[0]["author"] == "Kentaro Miura"
    assert context[0]["genres"] == ["Dark Fantasy"]
    assert context[0]["status"] == "läst"


def test_build_owned_context_unread_when_no_progress(db):
    user = _make_user(db)
    _add_book(db, title="Unread Book")
    assert build_owned_context(db, user)[0]["status"] == "oläst"


def test_build_owned_context_splits_evenly_across_library_types_despite_recency_skew(db, monkeypatch):
    """Regression test for the 2026-09-21 bug: a big, recent bulk import
    of one library_type must not crowd every other type out of the AI's
    context just because it's newer — see build_owned_context's own
    docstring. Simulates that exact shape: a small comics library added
    long ago, then a much larger manga library added just now.
    """
    user = _make_user(db)
    comics_library = Library(name="Comics", path="comics", library_type=LibraryType.COMICS)
    manga_library = Library(name="Manga", path="manga", library_type=LibraryType.MANGA)
    db.add_all([comics_library, manga_library])
    db.flush()

    def _add(library, title, added_at):
        book = Book(
            library_id=library.id,
            file_path=f"{title}.cbz",
            file_format=BookFormat.CBZ,
            file_size=1,
            file_mtime=0.0,
            added_at=added_at,
        )
        db.add(book)
        db.flush()
        db.add(BookMetadata(book_id=book.id, title=title, sort_title=title, authors=[], genres=[]))

    import datetime as dt

    for i in range(3):
        _add(comics_library, f"Comic {i}", dt.datetime(2026, 1, 1, tzinfo=dt.UTC) + dt.timedelta(days=i))
    for i in range(60):  # a bulk import much larger than _OWNED_LIBRARY_LIMIT on its own
        _add(manga_library, f"Manga {i}", dt.datetime(2026, 9, 21, tzinfo=dt.UTC) + dt.timedelta(minutes=i))
    db.commit()

    context = build_owned_context(db, user)
    titles = {item["title"] for item in context}

    assert any(title.startswith("Comic") for title in titles), (
        "comics were entirely crowded out by a newer manga import"
    )
    assert any(title.startswith("Manga") for title in titles)


def test_generate_raises_when_not_configured(db):
    user = _make_user(db)
    with pytest.raises(AIProviderError):
        generate_recommendations_for_user(db, user, _settings(ai_provider="", ai_api_key=""))


def test_generate_persists_suggestions_from_provider(db, monkeypatch):
    user = _make_user(db)
    _add_book(db, title="Owned Book")

    monkeypatch.setattr(
        recommendations_module,
        "generate_text",
        lambda *a, **kw: json.dumps(
            {
                "recommendations": [
                    {"title": "New Series", "author": "A. Author", "reason": "similar vibe", "media_type": "manga"}
                ]
            }
        ),
    )

    result = generate_recommendations_for_user(db, user, _settings())

    assert len(result) == 1
    assert result[0].title == "New Series"
    assert result[0].media_type_guess == RequestMediaType.MANGA
    assert result[0].status == AISuggestionStatus.SUGGESTED


def test_generate_persists_cover_url_from_fetch_cover_urls(db, monkeypatch):
    user = _make_user(db)
    _add_book(db, title="Owned Book")

    monkeypatch.setattr(
        recommendations_module,
        "generate_text",
        lambda *a, **kw: json.dumps({"recommendations": [{"title": "New Series", "media_type": "manga"}]}),
    )
    monkeypatch.setattr(
        recommendations_module, "fetch_cover_urls", lambda suggestions, **kw: ["https://covers.example/x.jpg"]
    )

    result = generate_recommendations_for_user(db, user, _settings())

    assert result[0].cover_url == "https://covers.example/x.jpg"


def test_generate_filters_out_already_owned_titles(db, monkeypatch):
    user = _make_user(db)
    _add_book(db, title="Already Owned")

    monkeypatch.setattr(
        recommendations_module,
        "generate_text",
        lambda *a, **kw: json.dumps({"recommendations": [{"title": "Already Owned"}, {"title": "Genuinely New"}]}),
    )

    result = generate_recommendations_for_user(db, user, _settings())

    assert [r.title for r in result] == ["Genuinely New"]


def test_generate_filters_out_previously_dismissed_titles(db, monkeypatch):
    user = _make_user(db)
    _add_book(db, title="Owned")
    db.add(AIRecommendation(user_id=user.id, title="Once Dismissed", status=AISuggestionStatus.DISMISSED))
    db.commit()

    monkeypatch.setattr(
        recommendations_module,
        "generate_text",
        lambda *a, **kw: json.dumps({"recommendations": [{"title": "Once Dismissed"}, {"title": "Fresh"}]}),
    )

    result = generate_recommendations_for_user(db, user, _settings())

    assert [r.title for r in result] == ["Fresh"]


def test_generate_filters_out_previously_requested_titles(db, monkeypatch):
    user = _make_user(db)
    _add_book(db, title="Owned")
    db.add(Request(requested_by_user_id=user.id, title="Already Requested", media_type=RequestMediaType.SERIES))
    db.commit()

    monkeypatch.setattr(
        recommendations_module,
        "generate_text",
        lambda *a, **kw: json.dumps({"recommendations": [{"title": "Already Requested"}, {"title": "Brand New"}]}),
    )

    result = generate_recommendations_for_user(db, user, _settings())

    assert [r.title for r in result] == ["Brand New"]


def test_generate_dedupes_duplicate_titles_within_one_batch(db, monkeypatch):
    user = _make_user(db)
    _add_book(db, title="Owned")

    monkeypatch.setattr(
        recommendations_module,
        "generate_text",
        lambda *a, **kw: json.dumps({"recommendations": [{"title": "Same Title"}, {"title": "same title"}]}),
    )

    result = generate_recommendations_for_user(db, user, _settings())
    assert len(result) == 1


def test_regenerate_replaces_suggested_but_keeps_requested_and_dismissed(db, monkeypatch):
    user = _make_user(db)
    _add_book(db, title="Owned")
    stale_suggested = AIRecommendation(user_id=user.id, title="Stale", status=AISuggestionStatus.SUGGESTED)
    kept_requested = AIRecommendation(user_id=user.id, title="Requested One", status=AISuggestionStatus.REQUESTED)
    kept_dismissed = AIRecommendation(user_id=user.id, title="Dismissed One", status=AISuggestionStatus.DISMISSED)
    db.add_all([stale_suggested, kept_requested, kept_dismissed])
    db.commit()

    monkeypatch.setattr(
        recommendations_module,
        "generate_text",
        lambda *a, **kw: json.dumps({"recommendations": [{"title": "Fresh Batch"}]}),
    )

    generate_recommendations_for_user(db, user, _settings())

    remaining_titles = {r.title for r in db.query(AIRecommendation).filter(AIRecommendation.user_id == user.id).all()}
    assert remaining_titles == {"Requested One", "Dismissed One", "Fresh Batch"}
