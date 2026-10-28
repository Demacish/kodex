"""The "Fortsätter läsa" shelf's card details — type chip, authors,
number, pages left and the EPUB chapter label (see
app/api/routes/reading_progress.py's continue_reading)."""

from __future__ import annotations

from app.models.book import Book
from app.models.enums import BookEditionType, BookFormat, LibraryType
from app.models.library import Library
from app.models.metadata import BookMetadata


def _seed_book(session_factory, *, library_type, file_format, page_count=None, number=None, authors=None) -> int:
    db = session_factory()
    library = Library(name=library_type.value, path=library_type.value, library_type=library_type)
    db.add(library)
    db.flush()
    book = Book(
        library_id=library.id,
        file_path=f"book.{file_format.value}",
        file_format=file_format,
        file_size=10,
        file_mtime=0.0,
        page_count=page_count,
        number=number,
        edition_type=BookEditionType.ISSUE,
    )
    db.add(book)
    db.flush()
    if authors is not None:
        db.add(BookMetadata(book_id=book.id, title="Boken", sort_title="boken", authors=authors))
    db.commit()
    book_id = book.id
    db.close()
    return book_id


def _shelf_item(client, book_id):
    return next(item for item in client.get("/me/continue-reading").json() if item["book_id"] == book_id)


def test_manga_card_has_type_number_authors_and_pages_left(api):
    client, session_factory = api
    book_id = _seed_book(
        session_factory,
        library_type=LibraryType.MANGA,
        file_format=BookFormat.CBZ,
        page_count=50,
        number=14,
        authors=["Kentaro Miura"],
    )
    # ImageReader saves a 0-based page index: index 7 = page 8 open.
    client.put(f"/books/{book_id}/progress", json={"position": "7", "progress_percent": 16})

    item = _shelf_item(client, book_id)
    assert item["library_type"] == "manga"
    assert item["file_format"] == "cbz"
    assert item["number"] == 14
    assert item["edition_type"] == "issue"
    assert item["authors"] == ["Kentaro Miura"]
    assert item["page_count"] == 50
    assert item["pages_left"] == 42
    assert item["chapter"] is None


def test_pdf_pages_left_uses_one_based_page_number(api):
    client, session_factory = api
    book_id = _seed_book(session_factory, library_type=LibraryType.EBOOKS, file_format=BookFormat.PDF, page_count=120)
    # PdfReader saves a 1-based page number: page 20 open = 100 left.
    client.put(f"/books/{book_id}/progress", json={"position": "20", "progress_percent": 17})

    assert _shelf_item(client, book_id)["pages_left"] == 100


def test_epub_card_has_chapter_and_no_pages_left(api):
    client, session_factory = api
    book_id = _seed_book(session_factory, library_type=LibraryType.EBOOKS, file_format=BookFormat.EPUB, page_count=300)
    client.put(
        f"/books/{book_id}/progress",
        json={"position": "epubcfi(/6/14!/4/2/1:0)", "progress_percent": 40, "chapter": "Kapitel 14"},
    )

    item = _shelf_item(client, book_id)
    assert item["library_type"] == "ebooks"
    assert item["chapter"] == "Kapitel 14"
    assert item["pages_left"] is None
    assert item["authors"] == []
    assert client.get(f"/books/{book_id}/progress").json()["chapter"] == "Kapitel 14"


def test_pages_left_is_none_without_page_count_or_numeric_position(api):
    client, session_factory = api
    no_count = _seed_book(session_factory, library_type=LibraryType.COMICS, file_format=BookFormat.CBR)
    client.put(f"/books/{no_count}/progress", json={"position": "3", "progress_percent": 10})
    assert _shelf_item(client, no_count)["pages_left"] is None
