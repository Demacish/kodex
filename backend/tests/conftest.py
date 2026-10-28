from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

# Every test talks to PostgreSQL, never SQLite: app.database builds its
# engine from DATABASE_URL at import time, so this has to be set before
# anything under app/ is imported. CI provides the database as a service;
# locally, tools/test-backend.sh starts one in Docker.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://kodex:kodex@localhost:5432/kodex_test")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import ipaddress
import socket

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.auth import get_current_user, require_admin, require_admin_or_upload_key
from app.database import engine, get_db
from app.main import app
from app.models.user import User
from kodex.core.migrate import upgrade_database
from tests.db import fresh_engine


def _forbid_network() -> None:
    """Tests never reach the network (docs/plan.sv.md, phase 1 gate):
    provider tests replay recorded or synthetic responses. Python sockets
    may only connect to this machine. The test database's host may be
    looked up (psycopg resolves it); libpq then connects without Python
    sockets."""
    from urllib.parse import urlsplit

    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo
    allowed = {"localhost", "testserver", urlsplit(TEST_DATABASE_URL).hostname}

    def is_local(host: object) -> bool:
        if host is None or host in allowed:
            return True
        try:
            return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
        except ValueError:
            return False

    def connect(self: socket.socket, address: object) -> None:
        host = address[0] if isinstance(address, tuple) else None
        if self.family != getattr(socket, "AF_UNIX", None) and not is_local(host):
            raise RuntimeError(f"tests must not use the network (connect to {address!r})")
        return real_connect(self, address)  # type: ignore[arg-type]

    def getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
        if not is_local(host):
            raise RuntimeError(f"tests must not use the network (lookup of {host!r})")
        return real_getaddrinfo(host, *args, **kwargs)  # type: ignore[arg-type]

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]


_forbid_network()

# The scanner only looks at file extensions when counting pages, never at
# image content, so arbitrary bytes are enough filler for "page" fixtures —
# no need to construct a real PNG.
_TINY_PNG = b"not-a-real-png-but-the-scanner-never-decodes-it"


COMICINFO_XML = """<?xml version="1.0" encoding="utf-8"?>
<ComicInfo>
  <Series>SeriesA</Series>
  <Title>SeriesA Volume {number}</Title>
  <Number>{number}</Number>
  <Summary>A test comic.</Summary>
  <Publisher>Test Publisher</Publisher>
  <Genre>Action, Adventure</Genre>
  <Writer>Ada Testwriter</Writer>
  <Year>2024</Year>
</ComicInfo>
"""

CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

CONTENT_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Standalone Test Book</dc:title>
    <dc:creator>Test Author</dc:creator>
    <dc:language>sv</dc:language>
    <dc:description>A standalone test EPUB.</dc:description>
  </metadata>
  <manifest>
    <item id="chapter1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter1"/>
  </spine>
</package>
"""

CHAPTER_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Hello, test.</p></body></html>
"""


def _write_cbz(path: Path, number: int) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("0001.png", _TINY_PNG)
        zf.writestr("0002.png", _TINY_PNG)
        zf.writestr("ComicInfo.xml", COMICINFO_XML.format(number=number))


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _write_cbr(path: Path, number: int, tmp_path: Path) -> None:
    """Copies a real, prebuilt RAR5 archive (see tests/fixtures/cbr/) so the
    test exercises the actual rarfile/unar code path rather than a fake.
    Only number 2 exists as a fixture.
    """
    assert number == 2, "only tests/fixtures/cbr/comicinfo_number_2.rar5.cbr exists"
    shutil.copyfile(FIXTURES_DIR / "cbr" / "comicinfo_number_2.rar5.cbr", path)


def _write_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("content.opf", CONTENT_OPF)
        zf.writestr("chapter1.xhtml", CHAPTER_XHTML)


@pytest.fixture
def library_root(tmp_path: Path) -> Path:
    root = tmp_path / "library_root"
    (root / "SeriesA").mkdir(parents=True)
    (root / "SeriesB" / "Chapter1").mkdir(parents=True)

    _write_cbz(root / "SeriesA" / "Volume 01.cbz", number=1)
    _write_cbr(root / "SeriesA" / "Volume 02.cbr", number=2, tmp_path=tmp_path)

    (root / "SeriesB" / "Chapter1" / "0001.png").write_bytes(_TINY_PNG)
    (root / "SeriesB" / "Chapter1" / "0002.png").write_bytes(_TINY_PNG)

    _write_epub(root / "Standalone Test Book.epub")

    return root


@pytest.fixture(scope="session", autouse=True)
def _test_schema():
    """Builds the schema once per run on a wiped database, through the
    Alembic migrations (never create_all), so every run also proves the
    migrations produce what the models describe."""
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    assert upgrade_database(engine) == []
    yield
    engine.dispose()


@pytest.fixture
def db_session():
    SessionLocal = sessionmaker(bind=fresh_engine())
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def api():
    """A TestClient wired to an isolated in-memory DB, with auth bypassed
    via a fixed admin user — shared by every test module that exercises
    the API layer (see test_api.py for the original, and test_collections.py
    / test_delivery.py for others that reuse it).
    """
    fresh_engine()
    TestingSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    fake_user = User(id=1, oidc_subject="test-sub", username="test", is_admin=True)

    # Persisted as a real row, not just held in memory — mirrors production,
    # where get_current_user (see app/auth.py) always upserts a real User
    # row for whoever's token this is. Needed for anything that joins back
    # to User via a relationship (e.g. Request.requested_by in
    # test_requests.py) rather than just storing a bare user_id column
    # (which SQLite's default no-FK-enforcement lets the rest of this
    # suite get away with never seeding). flush-then-expunge before commit
    # keeps `fake_user` itself a normal, attribute-populated detached
    # object afterwards, rather than expired and needing its now-closed
    # session to refresh it.
    seed_db = TestingSessionLocal()
    seed_db.add(fake_user)
    seed_db.flush()
    seed_db.expunge(fake_user)
    seed_db.commit()
    seed_db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[require_admin] = lambda: fake_user
    # require_admin_or_upload_key (B7's upload endpoint) can't be
    # bypassed via the two overrides above — see its own docstring: it
    # calls get_current_user/require_admin as plain Python functions, not
    # via their own Depends(), specifically so a missing/invalid bearer
    # token doesn't raise before the upload-key header even gets checked.
    # dependency_overrides only intercepts a callable that appears as
    # Depends(...) in a route's own signature, so it needs its own,
    # separate override here.
    app.dependency_overrides[require_admin_or_upload_key] = lambda: None

    with TestClient(app) as client:
        yield client, TestingSessionLocal

    app.dependency_overrides.clear()
