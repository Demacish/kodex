"""Tests for smart/manual collections: the rule compiler in
kodex/collections/rules.py (rules become SQL, evaluated per user), and the
CRUD + resolution endpoints in app/api/routes/collections.py. The `api`
fixture (shared with test_api.py, see conftest.py) gives a fixed admin
user, so every collection-management call in here is implicitly
admin-authorized.
"""

from __future__ import annotations

import pytest

from app.models.enums import BookFormat, LibraryType
from kodex.collections.rules import RuleError, single_story_arc, validate


@pytest.mark.parametrize(
    "rule",
    [
        {"field": "genres", "op": "eq", "value": "Fantasy"},
        {"field": "file_format", "op": "neq", "value": "cbz"},
        {"field": "library_id", "value": 3},
        {"all": [{"field": "genres", "value": "Fantasy"},
                 {"any": [{"field": "tags", "value": "Pirates"}, {"field": "tags", "value": "Ninjas"}]}]},
        {"not": {"field": "story_arcs", "value": 'Secret "Wars"'}},
        {"field": "title", "op": "contains", "value": "100%_"},
        {"field": "year", "op": "gte", "value": 1990},
        {"all": [{"field": "following", "value": True}, {"field": "next_unread", "value": True}]},
        {"field": "read_status", "op": "neq", "value": "finished"},
    ],
)  # fmt: skip
def test_valid_rules(rule):
    validate(rule)


@pytest.mark.parametrize(
    "rule",
    [
        {"field": "not_a_real_field", "value": "x"},
        {"field": "genres", "op": "startswith", "value": "x"},
        {"field": "genres", "op": "gte", "value": "x"},
        {"all": []},
        {"nonsense": True},
        {"field": "genres"},
        {"field": "library_id", "value": "three"},
        {"field": "file_format", "value": "docx"},
        {"field": "read_status", "value": "skimmed"},
        {"field": "next_unread", "value": False},
        "not an object",
    ],
)
def test_invalid_rules(rule):
    with pytest.raises(RuleError):
        validate(rule)


def test_single_story_arc():
    assert single_story_arc({"field": "story_arcs", "value": "Silent Tides"}) == "Silent Tides"
    assert single_story_arc({"field": "genres", "value": "Fantasy"}) is None
    assert single_story_arc({"all": [{"field": "story_arcs", "value": "Silent Tides"}]}) is None


def _seed_two_books(session_factory):
    from app.models.book import Book
    from app.models.library import Library

    db = session_factory()
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    book1 = Book(library_id=library.id, file_path="a.cbz", file_format=BookFormat.CBZ, file_size=1, file_mtime=0.0)
    book2 = Book(library_id=library.id, file_path="b.epub", file_format=BookFormat.EPUB, file_size=1, file_mtime=0.0)
    db.add_all([book1, book2])
    db.commit()
    ids = (book1.id, book2.id)
    db.close()
    return ids


def test_manual_collection_create_list_and_resolve(api):
    client, session_factory = api
    book1_id, book2_id = _seed_two_books(session_factory)

    response = client.post(
        "/collections",
        json={"name": "Favoriter", "collection_type": "manual", "book_ids": [book1_id]},
    )
    assert response.status_code == 201
    collection_id = response.json()["id"]
    assert response.json()["collection_type"] == "manual"

    listed = client.get("/collections").json()
    assert len(listed) == 1
    assert listed[0]["name"] == "Favoriter"

    books = client.get(f"/collections/{collection_id}/books").json()
    assert [b["id"] for b in books] == [book1_id]

    # Adding a second book, then removing the first, leaves only the second.
    add = client.post(f"/collections/{collection_id}/books", json=[book2_id])
    assert add.status_code == 204
    remove = client.delete(f"/collections/{collection_id}/books/{book1_id}")
    assert remove.status_code == 204

    books = client.get(f"/collections/{collection_id}/books").json()
    assert [b["id"] for b in books] == [book2_id]


def test_manual_collection_rejects_unknown_book_id(api):
    client, _ = api
    response = client.post("/collections", json={"name": "X", "collection_type": "manual", "book_ids": [999]})
    assert response.status_code == 404


def test_smart_collection_requires_rule(api):
    client, _ = api
    response = client.post("/collections", json={"name": "X", "collection_type": "smart"})
    assert response.status_code == 422  # pydantic model_validator rejects it before the route body runs


def test_smart_collection_rejects_bad_field_at_create_time(api):
    client, _ = api
    response = client.post(
        "/collections",
        json={"name": "X", "collection_type": "smart", "rule": {"field": "nope", "value": "x"}},
    )
    assert response.status_code == 400


def test_smart_collection_resolves_books_by_rule(api):
    client, session_factory = api
    book1_id, book2_id = _seed_two_books(session_factory)

    response = client.post(
        "/collections",
        json={"name": "CBZ-böcker", "collection_type": "smart", "rule": {"field": "file_format", "value": "cbz"}},
    )
    assert response.status_code == 201
    collection_id = response.json()["id"]
    books = client.get(f"/collections/{collection_id}/books")
    assert books.status_code == 200
    assert [b["id"] for b in books.json()] == [book1_id]
    listed = {c["id"]: c for c in client.get("/collections").json()}
    assert (listed[collection_id]["book_count"], listed[collection_id]["cover_book_id"]) == (1, book1_id)


def _seed_arc_books(session_factory):
    """Two books tagged with the same story arc but out of reading order:
    book "b" is StoryArcNumber 1 and book "a" StoryArcNumber 3, so a
    passing test proves the arc's order wins over the title order."""
    from app.models.book import Book
    from app.models.library import Library
    from app.models.metadata import BookMetadata

    db = session_factory()
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()

    book_a = Book(library_id=library.id, file_path="a.cbz", file_format=BookFormat.CBZ, file_size=1, file_mtime=0.0)
    book_b = Book(library_id=library.id, file_path="b.cbz", file_format=BookFormat.CBZ, file_size=1, file_mtime=0.0)
    db.add_all([book_a, book_b])
    db.flush()

    book_a.book_metadata = BookMetadata(
        book_id=book_a.id,
        title="a",
        sort_title="a",
        story_arcs=["Silent Tides"],
        story_arc_numbers={"Silent Tides": 3.0},
    )
    book_b.book_metadata = BookMetadata(
        book_id=book_b.id,
        title="b",
        sort_title="b",
        story_arcs=["Silent Tides"],
        story_arc_numbers={"Silent Tides": 1.0},
    )
    db.add_all([book_a.book_metadata, book_b.book_metadata])
    db.commit()
    ids = (book_a.id, book_b.id)
    db.close()
    return ids


def test_smart_collection_orders_by_story_arc_number(api):
    client, session_factory = api
    book_a_id, book_b_id = _seed_arc_books(session_factory)

    created = client.post(
        "/collections",
        json={
            "name": "Silent Tides",
            "collection_type": "smart",
            "rule": {"field": "story_arcs", "value": "Silent Tides"},
        },
    )
    collection_id = created.json()["id"]

    # Alphabetically a comes first; in the arc, b (#1) comes before a (#3).
    books = client.get(f"/collections/{collection_id}/books")

    assert books.status_code == 200
    assert [b["id"] for b in books.json()] == [book_b_id, book_a_id]


def test_reorder_manual_collection(api):
    client, session_factory = api
    book1_id, book2_id = _seed_two_books(session_factory)
    created = client.post(
        "/collections", json={"name": "X", "collection_type": "manual", "book_ids": [book1_id, book2_id]}
    )
    collection_id = created.json()["id"]

    reordered = client.put(f"/collections/{collection_id}/order", json=[book2_id, book1_id])
    assert reordered.status_code == 204

    books = client.get(f"/collections/{collection_id}/books").json()
    assert [b["id"] for b in books] == [book2_id, book1_id]

    listed = client.get("/collections").json()
    assert listed[0]["cover_book_id"] == book2_id


def test_reorder_rejects_partial_or_mismatched_book_ids(api):
    client, session_factory = api
    book1_id, book2_id = _seed_two_books(session_factory)
    created = client.post(
        "/collections", json={"name": "X", "collection_type": "manual", "book_ids": [book1_id, book2_id]}
    )
    collection_id = created.json()["id"]

    response = client.put(f"/collections/{collection_id}/order", json=[book1_id])
    assert response.status_code == 400


def test_reorder_rejects_smart_collection(api):
    client, _ = api
    created = client.post(
        "/collections",
        json={"name": "X", "collection_type": "smart", "rule": {"field": "genres", "value": "Fantasy"}},
    )
    collection_id = created.json()["id"]

    response = client.put(f"/collections/{collection_id}/order", json=[])
    assert response.status_code == 400


def test_collection_cover_upload_get_and_delete(api, tmp_path, monkeypatch):
    import app.api.routes.collections as collections_module
    from app.config import Settings

    monkeypatch.setattr(collections_module, "get_settings", lambda: Settings(covers_dir=tmp_path))

    client, _ = api
    created = client.post("/collections", json={"name": "X", "collection_type": "manual", "book_ids": []})
    collection_id = created.json()["id"]

    assert client.get(f"/collections/{collection_id}").json()["has_custom_cover"] is False
    assert client.get(f"/collections/{collection_id}/cover").status_code == 404

    upload = client.post(
        f"/collections/{collection_id}/cover",
        files={"file": ("cover.jpg", b"fake-image-bytes", "image/jpeg")},
    )
    assert upload.status_code == 204
    assert client.get(f"/collections/{collection_id}").json()["has_custom_cover"] is True

    fetched = client.get(f"/collections/{collection_id}/cover")
    assert fetched.status_code == 200
    assert fetched.content == b"fake-image-bytes"

    deleted = client.delete(f"/collections/{collection_id}/cover")
    assert deleted.status_code == 204
    assert client.get(f"/collections/{collection_id}").json()["has_custom_cover"] is False
    assert client.get(f"/collections/{collection_id}/cover").status_code == 404


def test_collection_cover_upload_rejects_unsupported_type(api, tmp_path, monkeypatch):
    import app.api.routes.collections as collections_module
    from app.config import Settings

    monkeypatch.setattr(collections_module, "get_settings", lambda: Settings(covers_dir=tmp_path))

    client, _ = api
    created = client.post("/collections", json={"name": "X", "collection_type": "manual", "book_ids": []})
    collection_id = created.json()["id"]

    response = client.post(
        f"/collections/{collection_id}/cover",
        files={"file": ("cover.gif", b"abc", "image/gif")},
    )
    assert response.status_code == 400


def test_update_collection_rule_validates_and_delete_removes_it(api):
    client, _ = api
    created = client.post(
        "/collections",
        json={"name": "X", "collection_type": "smart", "rule": {"field": "genres", "value": "Fantasy"}},
    )
    collection_id = created.json()["id"]

    bad_update = client.put(f"/collections/{collection_id}", json={"rule": {"field": "nope", "value": "x"}})
    assert bad_update.status_code == 400

    good_update = client.put(f"/collections/{collection_id}", json={"name": "Ny titel"})
    assert good_update.status_code == 200
    assert good_update.json()["name"] == "Ny titel"

    deleted = client.delete(f"/collections/{collection_id}")
    assert deleted.status_code == 204
    assert client.get(f"/collections/{collection_id}").status_code == 404


def test_generate_collection_returns_400_when_ai_not_configured(api, monkeypatch):
    import app.api.routes.collections as collections_module
    from app.config import Settings

    monkeypatch.setattr(collections_module, "get_settings", lambda: Settings(database_url="sqlite:///:memory:"))
    client, _ = api

    response = client.post("/collections/generate", json={"prompt": "rymdoperor"})
    assert response.status_code == 400


def test_generate_collection_creates_manual_collection_from_ai_picks(api, monkeypatch):
    import app.ai.collections as ai_collections_module
    import app.api.routes.collections as collections_module
    from app.config import Settings
    from app.models.book import Book
    from app.models.library import Library
    from app.models.metadata import BookMetadata

    monkeypatch.setattr(
        collections_module,
        "get_settings",
        lambda: Settings(database_url="sqlite:///:memory:", ai_provider="openai", ai_api_key="k"),
    )

    client, session_factory = api
    db = session_factory()
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    book = Book(library_id=library.id, file_path="saga.cbz", file_format=BookFormat.CBZ, file_size=1, file_mtime=0.0)
    db.add(book)
    db.flush()
    db.add(BookMetadata(book_id=book.id, title="Saga", sort_title="Saga"))
    db.commit()
    db.close()

    import json as json_module

    monkeypatch.setattr(
        ai_collections_module,
        "generate_text",
        lambda *a, **kw: json_module.dumps({"collection_name": "Rymdoperor", "books": [{"title": "Saga"}]}),
    )

    response = client.post("/collections/generate", json={"prompt": "rymdoperor"})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Rymdoperor"
    assert body["collection_type"] == "manual"
    assert body["book_count"] == 1


def test_generate_collection_returns_502_on_provider_error(api, monkeypatch):
    import app.ai.collections as ai_collections_module
    import app.api.routes.collections as collections_module
    from app.ai.base import AIProviderError
    from app.config import Settings
    from app.models.book import Book
    from app.models.library import Library
    from app.models.metadata import BookMetadata

    monkeypatch.setattr(
        collections_module,
        "get_settings",
        lambda: Settings(database_url="sqlite:///:memory:", ai_provider="openai", ai_api_key="k"),
    )

    client, session_factory = api
    db = session_factory()
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    book = Book(library_id=library.id, file_path="saga.cbz", file_format=BookFormat.CBZ, file_size=1, file_mtime=0.0)
    db.add(book)
    db.flush()
    db.add(BookMetadata(book_id=book.id, title="Saga", sort_title="Saga"))
    db.commit()
    db.close()

    def _boom(*a, **kw):
        raise AIProviderError("upstream failed")

    monkeypatch.setattr(ai_collections_module, "generate_text", _boom)

    response = client.post("/collections/generate", json={"prompt": "rymdoperor"})
    assert response.status_code == 502


def _seed_series(session_factory):
    """A series of four issues, the first two with Comic Vine ids."""
    from app.models.book import Book
    from app.models.library import Library
    from app.models.metadata import BookMetadata
    from app.models.series import Series

    with session_factory() as db:
        library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
        db.add(library)
        db.flush()
        series = Series(library_id=library.id, title="Stjärnhavet", sort_title="Stjärnhavet", path="s",
                        start_year=2019)  # fmt: skip
        db.add(series)
        db.flush()
        ids = []
        for number in (1, 2, 3, 4):
            book = Book(library_id=library.id, series_id=series.id, file_path=f"s/{number}.cbz", file_format=BookFormat.CBZ,
                        file_size=1, file_mtime=0.0, number=float(number))  # fmt: skip
            db.add(book)
            db.flush()
            external = {"comicvine_issue_id": 9000 + number, "comicvine_volume_id": 77} if number <= 2 else None
            db.add(BookMetadata(book_id=book.id, title=f"Stjärnhavet #{number}", sort_title=f"Stjärnhavet {number:03d}",
                                external_ids=external))  # fmt: skip
            ids.append(book.id)
        db.commit()
        return series.id, ids


def test_a_reading_list_goes_out_and_comes_back(api):
    from xml.etree import ElementTree as ET

    client, session_factory = api
    _, ids = _seed_series(session_factory)
    made = client.post("/collections", json={"name": "Min läsordning", "collection_type": "manual",
                                             "book_ids": ids[:3]})  # fmt: skip
    collection_id = made.json()["id"]
    assert client.put(f"/collections/{collection_id}/order", json=[ids[2], ids[0], ids[1]]).status_code == 204
    exported = client.get(f"/collections/{collection_id}/cbl")
    assert exported.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(exported.content)
    books = root.findall("Books/Book")
    assert [(b.get("Series"), b.get("Number"), b.get("Volume")) for b in books] == [
        ("Stjärnhavet", "3", "2019"), ("Stjärnhavet", "1", "2019"), ("Stjärnhavet", "2", "2019")]  # fmt: skip
    assert books[1].find("Database").attrib == {"Name": "cv", "Issue": "9001", "Series": "77"}

    # Back in, with one issue that isn't here and one found only by its cv id.
    extra = ET.SubElement(root.find("Books"), "Book", {"Series": "Stjärnhavet", "Number": "9"})
    by_id = ET.SubElement(root.find("Books"), "Book", {"Series": "Okänd titel", "Number": "1"})
    ET.SubElement(by_id, "Database", {"Name": "cv", "Issue": "9002"})
    assert extra is not None
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    imported = client.post("/collections/import-cbl", files={"file": ("lista.cbl", data, "application/xml")})
    assert imported.status_code == 201, imported.text
    body = imported.json()
    assert (body["matched"], body["collection"]["name"]) == (3, "Min läsordning")
    assert body["missing"] == [{"series": "Stjärnhavet", "number": "9", "volume": None, "year": None}]
    order = [b["id"] for b in client.get(f"/collections/{body['collection']['id']}/books").json()]
    assert order == [ids[2], ids[0], ids[1]]


def test_a_reading_list_with_entities_is_refused(api):
    client, _ = api
    bomb = b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa">]><ReadingList><Name>&a;</Name></ReadingList>'
    assert client.post("/collections/import-cbl", files={"file": ("x.cbl", bomb, "application/xml")}).status_code == 400
    assert (
        client.post("/collections/import-cbl", files={"file": ("x.cbl", b"<Other/>", "application/xml")}).status_code
        == 400
    )


def test_smart_rules_follow_the_reader(api):
    from app.models.reading_progress import ReadingProgress
    from app.models.series import Series

    client, session_factory = api
    series_id, ids = _seed_series(session_factory)
    with session_factory() as db:
        db.get(Series, series_id).is_following = True
        db.add(ReadingProgress(user_id=1, book_id=ids[0], progress_percent=100, is_finished=True))
        db.add(ReadingProgress(user_id=1, book_id=ids[1], progress_percent=40, is_finished=False))
        db.commit()

    def books(rule):
        made = client.post("/collections", json={"name": "Smart", "collection_type": "smart", "rule": rule})
        assert made.status_code == 201, made.text
        return [b["id"] for b in client.get(f"/collections/{made.json()['id']}/books").json()]

    assert books({"all": [{"field": "following", "value": True}, {"field": "next_unread", "value": True}]}) == [ids[1]]
    assert books({"field": "read_status", "value": "unread"}) == [ids[2], ids[3]]
    assert books({"field": "read_status", "value": "reading"}) == [ids[1]]
    assert books({"not": {"field": "read_status", "value": "finished"}}) == [ids[1], ids[2], ids[3]]
    assert books({"field": "series", "op": "contains", "value": "STJÄRN"}) == ids
    assert books(
        {"all": [{"field": "file_format", "value": "cbz"}, {"field": "title", "op": "contains", "value": "#4"}]}
    ) == [ids[3]]
