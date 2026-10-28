"""Tests for Send-to-Device: the CBZ/CBR->PDF conversion and mail-sending
logic in kodex/delivery/kindle.py, plus the API-level bits that don't need a
real SMTP server or Redis (see test_api.py's docstring on why queue
enqueue itself isn't exercised against a real Redis anywhere in this
suite — the same reasoning applies to the delivery queue).
"""

from __future__ import annotations

import smtplib
import zipfile
from pathlib import Path

import pikepdf
import pytest
from PIL import Image

from app.config import Settings
from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from kodex.delivery.kindle import DeliveryError, build_pdf_from_pages, send_book_to_kindle
from tests.pdf_helpers import page_sizes


def _make_settings(**overrides) -> Settings:
    defaults = dict(
        database_url="sqlite:///:memory:",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        smtp_from_address="reader@example.com",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _write_test_png(path: Path, width: int = 20, height: int = 30) -> None:
    Image.new("RGB", (width, height), "white").save(path, "PNG")


def test_build_pdf_from_pages_cbz(tmp_path: Path):
    page1 = tmp_path / "page1.png"
    page2 = tmp_path / "page2.png"
    _write_test_png(page1, width=20, height=30)
    _write_test_png(page2, width=40, height=10)

    cbz_path = tmp_path / "book.cbz"
    with zipfile.ZipFile(cbz_path, "w") as zf:
        zf.write(page1, "0001.png")
        zf.write(page2, "0002.png")

    dest = tmp_path / "out.pdf"
    build_pdf_from_pages(cbz_path, BookFormat.CBZ, 2, dest)

    # Each page keeps its own source image's aspect ratio/size, rather
    # than being forced onto one fixed page size.
    assert page_sizes(dest) == [(20, 30), (40, 10)]


def test_build_pdf_from_pages_embeds_jpeg_unchanged(tmp_path: Path):
    folder = tmp_path / "jpeg_pages"
    folder.mkdir()
    Image.new("RGB", (32, 48), "red").save(folder / "0001.jpg", "JPEG", quality=90)
    original = (folder / "0001.jpg").read_bytes()

    dest = tmp_path / "out.pdf"
    build_pdf_from_pages(folder, BookFormat.IMAGE_FOLDER, 1, dest)

    with pikepdf.open(dest) as pdf:
        image = next(iter(pdf.pages[0].get_images().values()))
        assert image.Filter == pikepdf.Name.DCTDecode
        assert image.read_raw_bytes() == original


def test_build_pdf_from_pages_image_folder(tmp_path: Path):
    folder = tmp_path / "loose_pages"
    folder.mkdir()
    _write_test_png(folder / "0001.png", width=15, height=15)
    _write_test_png(folder / "0002.png", width=15, height=15)

    dest = tmp_path / "out.pdf"
    build_pdf_from_pages(folder, BookFormat.IMAGE_FOLDER, 2, dest)

    assert len(page_sizes(dest)) == 2


class FakeSMTP:
    instances: list[FakeSMTP] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.started_tls = False
        self.logged_in = None
        self.sent_message = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.logged_in = (username, password)

    def send_message(self, message):
        self.sent_message = message


@pytest.fixture(autouse=True)
def _reset_fake_smtp_instances():
    FakeSMTP.instances.clear()
    yield
    FakeSMTP.instances.clear()


def _make_book(file_format: BookFormat, page_count: int | None = None) -> Book:
    book = Book(
        id=1,
        library_id=1,
        file_path="book",
        file_format=file_format,
        file_size=1,
        file_mtime=0.0,
        page_count=page_count,
    )
    return book


def test_send_book_to_kindle_requires_smtp_configured(tmp_path: Path):
    settings = _make_settings(smtp_host="")
    book = _make_book(BookFormat.EPUB)
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"fake epub bytes")

    with pytest.raises(DeliveryError):
        send_book_to_kindle(book, epub_path, "user@kindle.com", settings=settings)


def test_send_book_to_kindle_attaches_native_format_as_is(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    settings = _make_settings()
    book = _make_book(BookFormat.EPUB)
    epub_path = tmp_path / "mybook.epub"
    epub_path.write_bytes(b"fake epub bytes")

    send_book_to_kindle(book, epub_path, "user@kindle.com", settings=settings)

    assert len(FakeSMTP.instances) == 1
    smtp = FakeSMTP.instances[0]
    assert smtp.started_tls is True
    assert smtp.sent_message["To"] == "user@kindle.com"
    attachments = list(smtp.sent_message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_content_type() == "application/epub+zip"
    assert attachments[0].get_filename() == "mybook.epub"


def test_send_book_to_kindle_converts_cbz_to_pdf(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    settings = _make_settings()

    page_path = tmp_path / "page1.png"
    _write_test_png(page_path)
    cbz_path = tmp_path / "mycomic.cbz"
    with zipfile.ZipFile(cbz_path, "w") as zf:
        zf.write(page_path, "0001.png")

    book = _make_book(BookFormat.CBZ, page_count=1)
    send_book_to_kindle(book, cbz_path, "user@kindle.com", settings=settings)

    smtp = FakeSMTP.instances[0]
    attachments = list(smtp.sent_message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_content_type() == "application/pdf"
    assert attachments[0].get_filename() == "mycomic.pdf"


def test_send_book_to_kindle_requires_page_count_for_conversion(tmp_path: Path):
    settings = _make_settings()
    book = _make_book(BookFormat.CBZ, page_count=None)
    cbz_path = tmp_path / "mycomic.cbz"
    cbz_path.write_bytes(b"not read since we fail before that")

    with pytest.raises(DeliveryError):
        send_book_to_kindle(book, cbz_path, "user@kindle.com", settings=settings)


def _seed_ebook_and_library(session_factory) -> int:
    db = session_factory()
    library = Library(name="E-böcker", path="ebooks", library_type=LibraryType.EBOOKS)
    db.add(library)
    db.flush()
    book = Book(
        library_id=library.id, file_path="mybook.epub", file_format=BookFormat.EPUB, file_size=10, file_mtime=0.0
    )
    db.add(book)
    db.commit()
    book_id = book.id
    db.close()
    return book_id


def test_send_to_kindle_endpoint_rejects_missing_kindle_address(api):
    client, session_factory = api
    book_id = _seed_ebook_and_library(session_factory)

    response = client.post(f"/books/{book_id}/send-to-kindle")
    assert response.status_code == 400


def test_send_to_kindle_endpoint_enqueues_job_when_address_set(api, monkeypatch):
    client, session_factory = api
    book_id = _seed_ebook_and_library(session_factory)

    # The `api` fixture's fixed user has get_current_user overridden to
    # return the same Python object on every call (not re-read from the
    # DB), so giving it a kindle_email means overriding that dependency
    # again for this test rather than writing to the DB.
    from app.auth import get_current_user
    from app.main import app
    from app.models.user import User

    kindle_user = User(id=1, oidc_subject="test-sub", username="test", is_admin=True, kindle_email="user@kindle.com")
    app.dependency_overrides[get_current_user] = lambda: kindle_user

    calls = []

    class FakeQueue:
        def enqueue(self, func, *args):
            calls.append((func, args))

            class _Job:
                id = "fake-job-id"

            return _Job()

    monkeypatch.setattr("app.api.routes.books.get_delivery_queue", lambda: FakeQueue())

    response = client.post(f"/books/{book_id}/send-to-kindle")
    assert response.status_code == 202
    assert response.json() == {"job_id": "fake-job-id"}
    assert len(calls) == 1
    assert calls[0][1] == (book_id, 1)


def test_me_profile_get_and_update_kindle_email(api):
    client, _ = api

    profile = client.get("/me")
    assert profile.status_code == 200
    assert profile.json()["kindle_email"] is None
    assert profile.json()["has_opds_token"] is False

    bad = client.put("/me", json={"kindle_email": "not-an-email"})
    assert bad.status_code == 400

    good = client.put("/me", json={"kindle_email": "user@kindle.com"})
    assert good.status_code == 200
    assert good.json()["kindle_email"] == "user@kindle.com"

    cleared = client.put("/me", json={"kindle_email": ""})
    assert cleared.json()["kindle_email"] is None


def test_me_home_sections_default_null_then_updatable(api):
    client, _ = api

    profile = client.get("/me")
    assert profile.json()["home_sections"] is None  # no customization yet

    updated = client.put("/me", json={"home_sections": ["libraries", "continue_reading"]})
    assert updated.status_code == 200
    assert updated.json()["home_sections"] == ["libraries", "continue_reading"]

    # Persisted, not just echoed back.
    assert client.get("/me").json()["home_sections"] == ["libraries", "continue_reading"]

    emptied = client.put("/me", json={"home_sections": []})
    assert emptied.json()["home_sections"] == []  # hiding every section is a valid choice

    untouched = client.put("/me", json={"kindle_email": "user@kindle.com"})
    assert untouched.json()["home_sections"] == []  # omitted field leaves it unchanged


def test_me_home_sections_rejects_unknown_key(api):
    client, _ = api
    response = client.put("/me", json={"home_sections": ["not_a_real_section"]})
    assert response.status_code == 422


def test_me_home_sections_rejects_duplicates(api):
    client, _ = api
    response = client.put("/me", json={"home_sections": ["libraries", "libraries"]})
    assert response.status_code == 422
