"""v1's clients call the API through the old web app's proxy path,
/api/backend/<path> (kodex.core.legacy): the same routes answer it."""

from __future__ import annotations


def test_the_v1_proxy_path_reaches_the_same_routes(api):
    client, _ = api
    created = client.post("/libraries", json={"name": "Serier", "path": "serier", "library_type": "comics"})
    assert created.status_code == 201
    assert client.get("/api/backend/libraries").json() == client.get("/libraries").json()
    assert client.get("/api/backend/libraries?limit=1").status_code == 200
    assert client.get("/api/backend/libraries/999").status_code == 404


def test_only_the_whole_prefix_is_rewritten(api):
    client, _ = api
    assert client.get("/api/backendish/libraries").status_code == 404
