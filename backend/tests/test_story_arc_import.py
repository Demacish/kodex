"""Tests for C15's POST /collections/story-arc-import — building a smart
Collection + StoryArc from a bare Comic Vine story-arc id, then reusing
the existing on-demand roster-fetch job (refresh_story_arc_task). See
app/api/routes/collections.py's build_story_arc_collection.
"""

from __future__ import annotations

import app.api.routes.collections as collections_module
from app.config import Settings
from app.models.collection import Collection
from app.models.enums import CollectionType
from app.models.story_arc import StoryArc


class _FakeJob:
    id = "story-arc-job-id"


class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, func, *args, **kwargs):
        self.calls.append((func, args))
        return _FakeJob()


def _configure(monkeypatch, *, comicvine_api_key: str = "fake-key"):
    monkeypatch.setattr(
        collections_module,
        "get_settings",
        lambda: Settings(database_url="sqlite:///:memory:", comicvine_api_key=comicvine_api_key),
    )
    fake_queue = _FakeQueue()
    monkeypatch.setattr(collections_module, "get_enrichment_queue", lambda: fake_queue)
    return fake_queue


def test_build_story_arc_collection_with_explicit_name(api, monkeypatch):
    fake_queue = _configure(monkeypatch)
    client, session_factory = api

    response = client.post(
        "/collections/story-arc-import", json={"comicvine_story_arc_id": 12345, "name": "Silent Tides"}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"] == "story-arc-job-id"
    assert len(fake_queue.calls) == 1

    db = session_factory()
    collection = db.get(Collection, body["collection_id"])
    assert collection.name == "Silent Tides"
    assert collection.collection_type == CollectionType.SMART
    assert collection.rule == {"field": "story_arcs", "value": "Silent Tides"}
    story_arc = db.query(StoryArc).filter(StoryArc.collection_id == collection.id).one()
    assert story_arc.comicvine_id == 12345
    db.close()


def test_build_story_arc_collection_fetches_name_when_not_given(api, monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(collections_module, "fetch_arc_name", lambda arc_id, api_key: "Fetched Arc Name")
    client, session_factory = api

    response = client.post("/collections/story-arc-import", json={"comicvine_story_arc_id": 999})

    assert response.status_code == 202
    db = session_factory()
    collection = db.get(Collection, response.json()["collection_id"])
    assert collection.name == "Fetched Arc Name"
    db.close()


def test_build_story_arc_collection_requires_comicvine_api_key(api, monkeypatch):
    _configure(monkeypatch, comicvine_api_key="")
    client, _ = api

    response = client.post("/collections/story-arc-import", json={"comicvine_story_arc_id": 1, "name": "X"})
    assert response.status_code == 400


def test_build_story_arc_collection_502s_when_name_lookup_fails(api, monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(collections_module, "fetch_arc_name", lambda arc_id, api_key: None)
    client, _ = api

    response = client.post("/collections/story-arc-import", json={"comicvine_story_arc_id": 1})
    assert response.status_code == 502


def test_build_story_arc_collection_reuses_existing_collection_by_name(api, monkeypatch):
    fake_queue = _configure(monkeypatch)
    client, session_factory = api

    db = session_factory()
    rule = {"field": "story_arcs", "value": "Already Exists"}
    collection = Collection(name="Already Exists", collection_type=CollectionType.SMART, rule=rule)
    db.add(collection)
    db.commit()
    collection_id = collection.id
    db.close()

    response = client.post(
        "/collections/story-arc-import", json={"comicvine_story_arc_id": 55, "name": "Already Exists"}
    )

    assert response.status_code == 202
    assert response.json()["collection_id"] == collection_id
    assert len(fake_queue.calls) == 1


def test_build_story_arc_collection_second_call_for_same_arc_id_just_refreshes(api, monkeypatch):
    fake_queue = _configure(monkeypatch)
    client, session_factory = api

    first = client.post("/collections/story-arc-import", json={"comicvine_story_arc_id": 77, "name": "First Name"})
    assert first.status_code == 202
    collection_id = first.json()["collection_id"]

    second = client.post("/collections/story-arc-import", json={"comicvine_story_arc_id": 77, "name": "Ignored Name"})
    assert second.status_code == 202
    assert second.json()["collection_id"] == collection_id
    assert len(fake_queue.calls) == 2

    db = session_factory()
    assert db.query(Collection).count() == 1  # no duplicate collection created
    db.close()
