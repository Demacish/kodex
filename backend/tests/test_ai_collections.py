"""Tests for app/ai/collections.py — building the owned-library context,
fuzzy-matching the LLM's chosen titles back to real Book rows, and
generating an actual Collection from the result.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import sessionmaker

import app.ai.collections as collections_module
from app.ai.base import AIProviderError
from app.ai.collections import build_library_context, generate_collection_from_prompt
from app.config import Settings
from app.models.book import Book
from app.models.enums import BookFormat, CollectionType, LibraryType
from app.models.library import Library
from app.models.metadata import BookMetadata
from tests.db import fresh_engine


@pytest.fixture
def db():
    engine = fresh_engine()
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


def _add_book(db, *, title: str, authors=None) -> Book:
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
    db.add(BookMetadata(book_id=book.id, title=title, sort_title=title, authors=authors or []))
    db.commit()
    return book


def _settings(**overrides) -> Settings:
    defaults = dict(database_url="sqlite:///:memory:", ai_provider="claude", ai_api_key="claude-key")
    defaults.update(overrides)
    return Settings(**defaults)


def test_build_library_context_includes_book_id(db):
    book = _add_book(db, title="Saga", authors=["Brian K. Vaughan"])
    context = build_library_context(db)
    assert context[0]["id"] == book.id
    assert context[0]["title"] == "Saga"


def test_generate_raises_when_not_configured(db):
    _add_book(db, title="Owned")
    with pytest.raises(AIProviderError):
        generate_collection_from_prompt(db, prompt="rymdoperor", settings=_settings(ai_provider="", ai_api_key=""))


def test_generate_raises_when_library_empty(db):
    with pytest.raises(AIProviderError):
        generate_collection_from_prompt(db, prompt="rymdoperor", settings=_settings())


def test_generate_creates_manual_collection_from_matched_books(db, monkeypatch):
    saga = _add_book(db, title="Saga", authors=["Brian K. Vaughan"])
    _add_book(db, title="Cooking Manual")

    monkeypatch.setattr(
        collections_module,
        "generate_text",
        lambda *a, **kw: json.dumps(
            {
                "collection_name": "Rymdoperor",
                "books": [{"title": "Saga", "author": "Brian K. Vaughan", "reason": "space opera"}],
            }
        ),
    )

    collection = generate_collection_from_prompt(db, prompt="rymdoperor", settings=_settings())

    assert collection.name == "Rymdoperor"
    assert collection.collection_type == CollectionType.MANUAL
    assert [b.id for b in collection.books] == [saga.id]


def test_generate_fuzzy_matches_slightly_different_title(db, monkeypatch):
    compendium = _add_book(db, title="The Walking Dead Compendium 1")

    monkeypatch.setattr(
        collections_module,
        "generate_text",
        # A spelled-out "One" instead of the library's "1" — plausible
        # near-verbatim LLM echo, not a wholesale invented title.
        lambda *a, **kw: json.dumps({"collection_name": "X", "books": [{"title": "The Walking Dead Compendium One"}]}),
    )

    collection = generate_collection_from_prompt(db, prompt="theme", settings=_settings())
    assert [b.id for b in collection.books] == [compendium.id]


def test_generate_drops_hallucinated_title_not_in_library(db, monkeypatch):
    real = _add_book(db, title="Real Book")

    monkeypatch.setattr(
        collections_module,
        "generate_text",
        lambda *a, **kw: json.dumps(
            {"collection_name": "X", "books": [{"title": "Completely Made Up Title"}, {"title": "Real Book"}]}
        ),
    )

    collection = generate_collection_from_prompt(db, prompt="theme", settings=_settings())
    assert [b.id for b in collection.books] == [real.id]


def test_generate_raises_when_nothing_matches(db, monkeypatch):
    _add_book(db, title="Real Book")

    monkeypatch.setattr(
        collections_module,
        "generate_text",
        lambda *a, **kw: json.dumps({"collection_name": "X", "books": [{"title": "Nothing Like It"}]}),
    )

    with pytest.raises(AIProviderError):
        generate_collection_from_prompt(db, prompt="theme", settings=_settings())


def test_generate_uses_name_override_over_ai_suggested_name(db, monkeypatch):
    _add_book(db, title="Real Book")
    monkeypatch.setattr(
        collections_module,
        "generate_text",
        lambda *a, **kw: json.dumps({"collection_name": "AI Name", "books": [{"title": "Real Book"}]}),
    )

    collection = generate_collection_from_prompt(db, prompt="theme", settings=_settings(), name_override="My Name")
    assert collection.name == "My Name"


def test_generate_respects_library_id_filter(db, monkeypatch):
    lib_a = Library(name="A", path="a", library_type=LibraryType.COMICS)
    lib_b = Library(name="B", path="b", library_type=LibraryType.COMICS)
    db.add_all([lib_a, lib_b])
    db.flush()
    book_a = Book(library_id=lib_a.id, file_path="a.cbz", file_format=BookFormat.CBZ, file_size=1, file_mtime=0.0)
    book_b = Book(library_id=lib_b.id, file_path="b.cbz", file_format=BookFormat.CBZ, file_size=1, file_mtime=0.0)
    db.add_all([book_a, book_b])
    db.flush()
    db.add(BookMetadata(book_id=book_a.id, title="In A", sort_title="In A"))
    db.add(BookMetadata(book_id=book_b.id, title="In B", sort_title="In B"))
    db.commit()

    context = build_library_context(db, library_id=lib_a.id)
    assert [item["title"] for item in context] == ["In A"]
