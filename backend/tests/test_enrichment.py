"""Tests for the enrichment merge/dispatch logic in app/enrichment/engine.py.

These mock every provider call (monkeypatching the auto_match/fetch_details
functions) rather than hitting real APIs — the sandbox this code was
written in has no outbound network access to Comic Vine/AniList/Open
Library/Google Books at all (see the architecture plan's implementation
status note), so live calls have not been exercised. Verify those
separately once this runs somewhere with normal internet access.
"""

from __future__ import annotations

import pytest

from app.enrichment import anilist, comicvine, engine, google_books, open_library
from app.enrichment.base import EnrichmentResult
from app.models.book import Book
from app.models.enums import BookFormat, LibraryType, MetadataSource
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.series import Series

_library_counter = 0


def _make_book(
    db_session, *, library_type: LibraryType, with_metadata: bool = True, source=MetadataSource.EMBEDDED
) -> Book:
    global _library_counter
    _library_counter += 1
    library = Library(name="Test", path=f"test-{_library_counter}", library_type=library_type)
    db_session.add(library)
    db_session.flush()

    series = Series(library_id=library.id, title="Test Series", sort_title="Test Series", path="Test Series")
    db_session.add(series)
    db_session.flush()

    book = Book(
        library_id=library.id,
        series_id=series.id,
        file_path="Test Series/Volume 01.cbz",
        file_format=BookFormat.CBZ,
        file_size=100,
        file_mtime=0.0,
    )
    db_session.add(book)
    db_session.flush()

    if with_metadata:
        book.book_metadata = BookMetadata(book_id=book.id, title="Volume 01", sort_title="Volume 01", source=source)
        db_session.add(book.book_metadata)
        db_session.flush()

    return book


@pytest.fixture(autouse=True)
def no_real_cover_downloads(monkeypatch):
    # Every test in this file should avoid touching the network for covers.
    monkeypatch.setattr(engine, "download_cover", lambda url, book_id, **kw: f"{book_id}.jpg")


def test_provider_for_book_dispatches_by_library_type(db_session):
    comics_book = _make_book(db_session, library_type=LibraryType.COMICS)
    manga_book = _make_book(db_session, library_type=LibraryType.MANGA)
    ebook = _make_book(db_session, library_type=LibraryType.EBOOKS)

    assert engine.provider_for_book(comics_book) == "comicvine"
    assert engine.provider_for_book(manga_book) == "anilist"
    assert engine.provider_for_book(ebook) == "open_library"


def test_search_query_prefers_embedded_title_over_mangled_ebook_folder_name(db_session):
    """Regression test for 2026-09-21: an ebook's folder is usually just a
    filesystem-safe slug (no spaces/punctuation — e.g. "lanternpocketref"),
    unlike a comic's scene-release folder name, which the sorting parser
    is actually built to extract a clean series name from. Using the
    folder name for an ebook produced search queries so mangled every
    Open Library/Google Books search came up empty (0/131 in the
    library this was found in) — book_metadata's own title must win for
    EBOOKS libraries specifically.
    """
    library = Library(name="Ebooks", path="ebooks-test", library_type=LibraryType.EBOOKS)
    db_session.add(library)
    db_session.flush()
    book = Book(
        library_id=library.id,
        file_path="lanternpocketref/lanternpocketref.pdf",
        file_format=BookFormat.PDF,
        file_size=100,
        file_mtime=0.0,
    )
    db_session.add(book)
    db_session.flush()
    book.book_metadata = BookMetadata(
        book_id=book.id, title="Lantern Pocket Reference", sort_title="Lantern Pocket Reference"
    )
    db_session.add(book.book_metadata)
    db_session.flush()

    query, number = engine._search_query_and_number(book)

    assert query == "Lantern Pocket Reference"
    assert number is None


def test_search_query_still_prefers_folder_name_for_comics(db_session):
    """Regression guard: the ebook-specific fix above must not change
    comics' existing (working — 253/253 covers) behavior, where the
    scene-release folder name is the reliable source of a clean series
    name + issue number, not book_metadata.title (which before a match
    is often still the raw messy scanned title).
    """
    library = Library(name="Comics", path="comics-test", library_type=LibraryType.COMICS)
    db_session.add(library)
    db_session.flush()
    book = Book(
        library_id=library.id,
        file_path="Absolute Corvid 001 (2024)/file.cbz",
        file_format=BookFormat.CBZ,
        file_size=100,
        file_mtime=0.0,
    )
    db_session.add(book)
    db_session.flush()
    book.book_metadata = BookMetadata(book_id=book.id, title="Absolute Corvid 001 (2024)", sort_title="x")
    db_session.add(book.book_metadata)
    db_session.flush()

    query, number = engine._search_query_and_number(book)

    assert query == "Absolute Corvid"
    assert number == 1


def test_auto_enrich_fills_blank_fields_only(db_session, monkeypatch):
    book = _make_book(db_session, library_type=LibraryType.MANGA)
    # Pre-existing field that enrichment must NOT clobber.
    book.book_metadata.publisher = "Existing Publisher"
    db_session.add(book.book_metadata)
    db_session.commit()

    fake_result = EnrichmentResult(
        title="Real Title",
        genres=["Action", "Fantasy"],
        summary="A summary from AniList.",
        publisher="AniList Publisher",  # should be ignored — publisher already set
        published_year=2020,
        cover_url="https://example.com/cover.jpg",
        external_ids={"anilist_id": 42},
    )
    monkeypatch.setattr(anilist, "auto_match", lambda *a, **kw: fake_result)

    # force=True: publisher already being set makes this metadata "not
    # thin" by is_thin()'s definition, so the ordinary automatic path
    # would skip it entirely — force bypasses that so we can specifically
    # exercise "existing fields survive, blank ones get filled".
    changed = engine.auto_enrich_book(db_session, book, force=True)
    db_session.commit()

    assert changed is True
    meta = book.book_metadata
    assert meta.publisher == "Existing Publisher"  # untouched
    assert meta.genres == ["Action", "Fantasy"]  # filled in
    assert meta.summary == "A summary from AniList."
    assert meta.published_year == 2020
    assert meta.cover_path == f"{book.id}.jpg"
    assert meta.external_ids == {"anilist_id": 42}
    assert meta.source == MetadataSource.ENRICHED
    assert meta.enriched_at is not None


def test_auto_enrich_skips_manual_rows(db_session, monkeypatch):
    book = _make_book(db_session, library_type=LibraryType.MANGA, source=MetadataSource.MANUAL)
    db_session.commit()

    called = False

    def fake_auto_match(*a, **kw):
        nonlocal called
        called = True
        return EnrichmentResult(summary="should never be applied")

    monkeypatch.setattr(anilist, "auto_match", fake_auto_match)

    changed = engine.auto_enrich_book(db_session, book, force=True)

    assert changed is False
    assert called is False  # never even attempted a lookup for a MANUAL row
    assert book.book_metadata.summary is None


def test_auto_enrich_skips_non_thin_metadata_unless_forced(db_session, monkeypatch):
    book = _make_book(db_session, library_type=LibraryType.MANGA)
    book.book_metadata.summary = "Already has a summary"
    book.book_metadata.genres = ["Comedy"]
    book.book_metadata.authors = ["Someone"]
    book.book_metadata.publisher = "Someone Publishing"
    db_session.commit()

    monkeypatch.setattr(
        anilist, "auto_match", lambda *a, **kw: EnrichmentResult(summary="new summary that should be ignored")
    )

    changed = engine.auto_enrich_book(db_session, book)  # not thin -> skipped
    assert changed is False
    assert book.book_metadata.summary == "Already has a summary"

    changed = engine.auto_enrich_book(
        db_session, book, force=True
    )  # forced -> attempted, but summary stays (not blank)
    assert changed is False
    assert book.book_metadata.summary == "Already has a summary"


def test_comicvine_enrichment_requires_api_key(db_session, monkeypatch):
    book = _make_book(db_session, library_type=LibraryType.COMICS)

    calls = []
    monkeypatch.setattr(comicvine, "auto_match", lambda *a, **kw: calls.append(1))

    changed = engine.auto_enrich_book(db_session, book, comicvine_api_key="")

    assert changed is False
    assert calls == []  # skipped entirely without a key — auto_match never even called


def test_manual_match_overwrites_and_locks_to_manual(db_session, monkeypatch):
    book = _make_book(db_session, library_type=LibraryType.EBOOKS)
    book.book_metadata.genres = ["Old genre"]
    db_session.commit()

    fake_result = EnrichmentResult(
        title="Correct Title",
        authors=["Correct Author"],
        genres=["Correct Genre"],
        external_ids={"open_library_key": "/works/OL999W"},
    )
    monkeypatch.setattr(open_library, "fetch_details", lambda *a, **kw: fake_result)

    changed = engine.apply_manual_match(db_session, book, "open_library", "/works/OL999W")
    db_session.commit()

    assert changed is True
    meta = book.book_metadata
    assert meta.title == "Correct Title"
    assert meta.genres == ["Correct Genre"]  # overwritten, unlike the automatic path
    assert meta.source == MetadataSource.MANUAL

    # A subsequent automatic run must leave this book alone entirely now.
    monkeypatch.setattr(open_library, "auto_match", lambda *a, **kw: EnrichmentResult(genres=["Should never apply"]))
    monkeypatch.setattr(google_books, "auto_match", lambda *a, **kw: EnrichmentResult(genres=["Should never apply"]))
    changed_again = engine.auto_enrich_book(db_session, book, force=True)
    assert changed_again is False
    assert meta.genres == ["Correct Genre"]


def test_manual_match_with_fields_only_replaces_chosen_fields(db_session, monkeypatch):
    book = _make_book(db_session, library_type=LibraryType.EBOOKS)
    book.book_metadata.genres = ["Old genre"]
    book.book_metadata.summary = "My own summary, keep this"
    db_session.commit()

    fake_result = EnrichmentResult(
        title="Correct Title",
        authors=["Correct Author"],
        genres=["Correct Genre"],
        summary="Provider summary — should be rejected",
        external_ids={"open_library_key": "/works/OL999W"},
    )
    monkeypatch.setattr(open_library, "fetch_details", lambda *a, **kw: fake_result)

    changed = engine.apply_manual_match(db_session, book, "open_library", "/works/OL999W", fields={"authors", "genres"})
    db_session.commit()

    assert changed is True
    meta = book.book_metadata
    assert meta.authors == ["Correct Author"]
    assert meta.genres == ["Correct Genre"]
    # Not in `fields` — kept as-is despite the provider offering a value.
    assert meta.summary == "My own summary, keep this"
    assert meta.title == "Volume 01"  # not in `fields` either
    # external_ids is never gated by `fields` — always merges (identity data).
    assert meta.external_ids == {"open_library_key": "/works/OL999W"}
    assert meta.source == MetadataSource.MANUAL


def test_manual_match_with_empty_fields_set_changes_nothing_but_locks_manual(db_session, monkeypatch):
    book = _make_book(db_session, library_type=LibraryType.EBOOKS)
    fake_result = EnrichmentResult(
        title="New Title", authors=["New Author"], external_ids={"open_library_key": "/works/OL1W"}
    )
    monkeypatch.setattr(open_library, "fetch_details", lambda *a, **kw: fake_result)

    changed = engine.apply_manual_match(db_session, book, "open_library", "/works/OL1W", fields=set())

    # external_ids still merges even with an empty selection — the only
    # change here, which is enough to flip changed=True and lock the row.
    assert changed is True
    assert book.book_metadata.title == "Volume 01"
    assert book.book_metadata.authors == []


def test_compute_field_diff_only_includes_non_empty_incoming_values(db_session):
    book = _make_book(db_session, library_type=LibraryType.EBOOKS)
    book.book_metadata.summary = "Existing summary"
    db_session.commit()

    result = EnrichmentResult(title="New Title", authors=["A"], summary="", genres=[])

    diff = engine.compute_field_diff(book, result)

    assert diff["title"] == {"current": "Volume 01", "incoming": "New Title"}
    assert diff["authors"] == {"current": [], "incoming": ["A"]}
    # Empty-string/empty-list incoming values are skipped, same as maybe_set.
    assert "summary" not in diff
    assert "genres" not in diff


def test_preview_manual_match_returns_diff_without_writing(db_session, monkeypatch):
    book = _make_book(db_session, library_type=LibraryType.EBOOKS)
    fake_result = EnrichmentResult(title="Previewed Title", authors=["Preview Author"])
    monkeypatch.setattr(open_library, "fetch_details", lambda *a, **kw: fake_result)

    diff = engine.preview_manual_match(book, "open_library", "/works/OL1W")

    assert diff["title"]["incoming"] == "Previewed Title"
    # No DB write happened — still the original scanner-seeded title.
    assert book.book_metadata.title == "Volume 01"
    assert book.book_metadata.source == MetadataSource.EMBEDDED


def test_preview_manual_match_returns_none_when_provider_has_nothing(db_session, monkeypatch):
    book = _make_book(db_session, library_type=LibraryType.EBOOKS)
    monkeypatch.setattr(open_library, "fetch_details", lambda *a, **kw: None)

    assert engine.preview_manual_match(book, "open_library", "/works/unknown") is None


def test_search_provider_dispatch_and_unknown_provider(monkeypatch):
    monkeypatch.setattr(open_library, "search", lambda query, **kw: ["fake-candidate"])
    assert engine.search_provider("open_library", "Some Book") == ["fake-candidate"]

    with pytest.raises(ValueError):
        engine.search_provider("not-a-real-provider", "x")


def test_apply_manual_match_with_issue_id_reparents_series(db_session, monkeypatch):
    book = _make_book(db_session, library_type=LibraryType.COMICS)

    fake_result = EnrichmentResult(
        title="Issue Title",
        series_title="Test Series",
        summary="Issue summary",
        external_ids={"comicvine_issue_id": 555, "comicvine_volume_id": 111},
    )
    monkeypatch.setattr(comicvine, "fetch_issue_details", lambda issue_id, api_key, **kw: fake_result)

    changed = engine.apply_manual_match(db_session, book, "comicvine", "555", is_issue=True, comicvine_api_key="key")
    db_session.commit()

    assert changed is True
    assert book.book_metadata.title == "Issue Title"
    assert book.book_metadata.source == MetadataSource.MANUAL
    # The picked issue's own volume id reparents the book the same way a
    # volume-level match does — see _reparent_to_canonical_series.
    assert book.series.comicvine_volume_id == 111


def test_list_issues_for_volume_rejects_non_comicvine():
    with pytest.raises(ValueError):
        engine.list_issues_for_volume("anilist", "123", "key")


def test_list_issues_for_volume_dispatches_to_comicvine(monkeypatch):
    monkeypatch.setattr(comicvine, "list_issues", lambda volume_id, api_key, **kw: ["fake-issue"])
    assert engine.list_issues_for_volume("comicvine", "123", "key") == ["fake-issue"]


def test_list_issues_for_volume_skips_without_api_key():
    assert engine.list_issues_for_volume("comicvine", "123", "") == []


def test_auto_enrich_only_fills_details_for_a_series_the_engine_matched(db_session, monkeypatch):
    """Once kodex.matching has matched the series, v1 enrichment fetches the
    chosen issue's details and neither searches nor changes ids."""
    from app.enrichment import comicvine as comicvine_module
    from app.enrichment import engine as engine_module
    from app.enrichment.base import EnrichmentResult
    from app.models.book import Book
    from app.models.enums import BookFormat, LibraryType, MetadataSource
    from app.models.library import Library
    from app.models.metadata import BookMetadata
    from app.models.series import Series

    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db_session.add(library)
    db_session.flush()
    series = Series(library_id=library.id, title="Saga", sort_title="Saga", path="Saga", match_status="auto")
    db_session.add(series)
    db_session.flush()
    book = Book(library_id=library.id, series_id=series.id, file_path="Saga/1.cbz", file_format=BookFormat.CBZ,
                file_size=1, file_mtime=1.0)  # fmt: skip
    db_session.add(book)
    db_session.flush()
    book.book_metadata = BookMetadata(book_id=book.id, title="1", sort_title="1", source=MetadataSource.EMBEDDED,
                                      external_ids={"comicvine_issue_id": "321297"}, locked_fields=["summary"])  # fmt: skip
    db_session.commit()

    monkeypatch.setattr(comicvine_module, "auto_match", lambda *a, **k: pytest.fail("must not search"))
    monkeypatch.setattr(
        comicvine_module,
        "fetch_issue_details",
        lambda issue_id, key, **k: EnrichmentResult(
            title="Chapter One", summary="New summary", publisher="Image", external_ids={"comicvine_issue_id": 999}
        ),  # fmt: skip
    )

    assert engine_module.auto_enrich_book(db_session, book, comicvine_api_key="k") is True
    meta = book.book_metadata
    assert (meta.title, meta.publisher, meta.summary) == ("Chapter One", "Image", None)  # summary is locked
    assert meta.external_ids["comicvine_issue_id"] == "321297"
