"""Search in PostgreSQL (kodex.discovery.search, through /api/search):
titles, series, authors, typos, CJK titles and summaries for books, and
book text with a highlighted, escaped snippet; and the full-text job's
extraction from EPUB and PDF into content_index_entries."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app.config import Settings
from app.models.book import Book
from app.models.content_index import ContentIndexEntry
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.series import Series
from app.search import fulltext as fulltext_module
from app.search.fulltext import extract_epub_chapters, extract_pdf_pages, index_book_fulltext, index_library_fulltext
from tests.pdf_helpers import write_text_pdf


@pytest.fixture
def shelf(api):
    """A library of a few series and books; returns their ids by name."""
    client, session_factory = api
    ids: dict[str, int] = {}
    with session_factory() as db:
        comics = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
        manga = Library(name="Manga", path="manga", library_type=LibraryType.MANGA)
        db.add_all([comics, manga])
        db.flush()
        ids["comics"], ids["manga"] = comics.id, manga.id
        books = [
            ("stjarn1", comics, "Stjärnhavet", "Stjärnhavet #1", ["Ingrid Berg"], "Ett skepp seglar mot okända öar."),
            ("stjarn2", comics, "Stjärnhavet", "Stjärnhavet #2", ["Ingrid Berg"], None),
            ("skog", comics, "Skogens väktare", "Skogens väktare #1", ["Pelle Ek"], "Vargarna vaknar i norr."),
            ("titan", manga, "進撃の巨人", "進撃の巨人 1", ["諫山創"], None),
        ]
        series: dict[str, Series] = {}
        for key, library, series_title, title, authors, summary in books:
            if series_title not in series:
                series[series_title] = Series(library_id=library.id, title=series_title, sort_title=series_title,
                                              path=series_title)  # fmt: skip
                db.add(series[series_title])
                db.flush()
            book = Book(library_id=library.id, series_id=series[series_title].id, file_path=f"{key}.cbz",
                        file_format=BookFormat.CBZ, file_size=1, file_mtime=0.0, number=1.0)  # fmt: skip
            db.add(book)
            db.flush()
            db.add(BookMetadata(book_id=book.id, title=title, sort_title=title, authors=authors, summary=summary))
            ids[key] = book.id
        ids["series:skog"] = series["Skogens väktare"].id
        db.commit()
    return client, session_factory, ids


def _found(client, q: str, **params) -> list[int]:
    response = client.get("/api/search/books", params={"q": q, **params})
    assert response.status_code == 200, response.text
    return [hit["book_id"] for hit in response.json()]


def test_titles_series_and_authors_are_found(shelf):
    client, _, ids = shelf
    assert set(_found(client, "stjärnhavet")) == {ids["stjarn1"], ids["stjarn2"]}
    assert _found(client, "stjärnhavet 2")[0] == ids["stjarn2"]
    assert _found(client, "pelle ek") == [ids["skog"]]
    hit = client.get("/api/search/books", params={"q": "väktare"}).json()[0]
    assert (hit["series_title"], hit["library_name"], hit["file_format"]) == ("Skogens väktare", "Serier", "cbz")


def test_a_typo_is_forgiven(shelf):
    client, _, ids = shelf
    assert ids["skog"] in _found(client, "skogens vaktare")


def test_cjk_titles_without_spaces_are_found(shelf):
    client, _, ids = shelf
    assert _found(client, "巨人") == [ids["titan"]]
    assert _found(client, "諫山") == [ids["titan"]]


def test_summaries_are_searched_as_text(shelf):
    client, _, ids = shelf
    assert _found(client, "vargarna") == [ids["skog"]]
    assert _found(client, "skepp öar") == [ids["stjarn1"]]


def test_search_is_scoped_and_skips_missing_books(shelf):
    client, session_factory, ids = shelf
    assert _found(client, "1", library_id=ids["manga"]) == [ids["titan"]]
    assert _found(client, "väktare", series_id=ids["series:skog"]) == [ids["skog"]]
    with session_factory() as db:
        db.get(Book, ids["skog"]).missing_since = dt.datetime.now(dt.UTC)
        db.commit()
    assert _found(client, "väktare") == []
    assert _found(client, "   ") == []


def test_book_text_is_searched_with_an_escaped_snippet(shelf):
    client, session_factory, ids = shelf
    with session_factory() as db:
        db.add(ContentIndexEntry(book_id=ids["stjarn1"], position="chapter3.xhtml",
                                 text="Kaptenen skrev <script>alert(1)</script> i loggboken innan stormen kom."))  # fmt: skip
        db.add(ContentIndexEntry(book_id=ids["skog"], position="2", text="Ingen storm här, bara skog."))
        db.commit()
    hits = client.get("/api/search/fulltext", params={"q": "loggboken"}).json()
    assert [(h["book_id"], h["position"], h["title"]) for h in hits] == [
        (ids["stjarn1"], "chapter3.xhtml", "Stjärnhavet #1")
    ]
    assert "<mark>loggboken</mark>" in hits[0]["snippet"] and "<script>" not in hits[0]["snippet"]
    both = client.get("/api/search/fulltext", params={"q": "storm"}).json()
    assert {h["book_id"] for h in both} == {ids["skog"]}  # "stormen" is another word without stemming
    scoped = client.get("/api/search/fulltext", params={"q": "storm", "book_id": ids["stjarn1"]}).json()
    assert scoped == []


def test_extract_epub_chapters(library_root: Path):
    chapters = extract_epub_chapters(library_root / "Standalone Test Book.epub")
    assert chapters == [("chapter1.xhtml", "Hello, test.")]


def test_extract_pdf_pages(tmp_path: Path):
    pdf_path = write_text_pdf(tmp_path / "test.pdf", ["Hello PDF world", "", "Third page"])

    pages = extract_pdf_pages(pdf_path)

    # The empty second page is skipped; positions are 1-based page numbers.
    assert [position for position, _ in pages] == ["1", "3"]
    assert "Hello" in pages[0][1]
    assert "world" in pages[0][1]


def test_index_book_fulltext_extracts_and_indexes_epub(db_session, library_root: Path, monkeypatch):
    stub_settings = Settings(libraries_root=library_root.parent, database_url="sqlite:///:memory:")
    monkeypatch.setattr(fulltext_module, "get_settings", lambda: stub_settings)

    library = Library(name="Test", path=library_root.name, library_type=LibraryType.EBOOKS)
    db_session.add(library)
    db_session.flush()
    book = Book(
        library_id=library.id,
        file_path="Standalone Test Book.epub",
        file_format=BookFormat.EPUB,
        file_size=1,
        file_mtime=0.0,
    )
    db_session.add(book)
    db_session.flush()

    count = index_book_fulltext(db_session, book)

    assert count == 1
    entry = db_session.query(ContentIndexEntry).one()
    assert (entry.book_id, entry.position, entry.text) == (book.id, "chapter1.xhtml", "Hello, test.")


def test_index_book_fulltext_skips_cbz(db_session, library_root: Path, monkeypatch):
    stub_settings = Settings(libraries_root=library_root.parent, database_url="sqlite:///:memory:")
    monkeypatch.setattr(fulltext_module, "get_settings", lambda: stub_settings)

    library = Library(name="Test", path=library_root.name, library_type=LibraryType.COMICS)
    db_session.add(library)
    db_session.flush()
    book = Book(
        library_id=library.id,
        file_path="SeriesA/Volume 01.cbz",
        file_format=BookFormat.CBZ,
        file_size=1,
        file_mtime=0.0,
    )
    db_session.add(book)
    db_session.flush()

    assert index_book_fulltext(db_session, book) == 0


def test_index_library_fulltext_reports_totals(db_session, library_root: Path, monkeypatch):
    stub_settings = Settings(libraries_root=library_root.parent, database_url="sqlite:///:memory:")
    monkeypatch.setattr(fulltext_module, "get_settings", lambda: stub_settings)

    library = Library(name="Test", path=library_root.name, library_type=LibraryType.MIXED)
    db_session.add(library)
    db_session.flush()
    epub = Book(
        library_id=library.id,
        file_path="Standalone Test Book.epub",
        file_format=BookFormat.EPUB,
        file_size=1,
        file_mtime=0.0,
    )
    cbz = Book(
        library_id=library.id,
        file_path="SeriesA/Volume 01.cbz",
        file_format=BookFormat.CBZ,
        file_size=1,
        file_mtime=0.0,
    )
    db_session.add_all([epub, cbz])
    db_session.commit()

    result = index_library_fulltext(db_session, library)

    # CBZ is filtered out of the query entirely (image-only format), so only
    # the EPUB is "considered".
    assert result == {"books_considered": 1, "books_indexed": 1, "entries_indexed": 1}
