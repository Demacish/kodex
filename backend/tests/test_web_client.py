"""The api serves the web client (kodex.core.spa) and the API under /api,
documented by /api/openapi.json, while v1's routes stay at the root."""

from __future__ import annotations

from collections import Counter

import pytest
from fastapi.testclient import TestClient

from app.main import app
from kodex.core.spa import WebClient
from tests.db import reset_database

_PAGE = {"sec-fetch-dest": "document", "accept": "text/html"}


@pytest.fixture
def web(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>Kodex</title>")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)")
    (tmp_path / "sw.js").write_text("self")
    reset_database()
    with TestClient(WebClient(app, tmp_path)) as client:
        yield client


def test_pages_get_the_web_client(web):
    for path in ("/", "/series/12", "/admin/review", "/login"):
        response = web.get(path, headers=_PAGE)
        assert response.status_code == 200 and "<title>Kodex</title>" in response.text, path
        assert response.headers["cache-control"] == "no-cache"
        assert "script-src 'self' 'wasm-unsafe-eval'" in response.headers["content-security-policy"]
    old_browser = web.get("/series/12", headers={"accept": "text/html,application/xhtml+xml"})
    assert "<title>Kodex</title>" in old_browser.text


def test_the_page_answers_by_name_for_the_service_worker(web):
    response = web.get("/index.html")
    assert "<title>Kodex</title>" in response.text and "content-security-policy" in response.headers


def test_files_are_served_with_their_caching(web):
    asset = web.get("/assets/index-abc123.js")
    assert asset.text == "console.log(1)" and "immutable" in asset.headers["cache-control"]
    assert web.get("/sw.js").headers["cache-control"] == "no-cache"


def test_api_calls_are_left_to_the_api(web):
    assert web.get("/series/12").status_code == 401  # v1's route, as a fetch
    assert web.get("/api/series/12", headers=_PAGE).status_code == 401
    assert web.get("/opds", headers=_PAGE).status_code == 401
    assert web.get("/healthz", headers=_PAGE).json() == {"status": "ok"}
    assert web.post("/series/12", headers=_PAGE).status_code in (401, 405)


def test_without_a_build_only_the_api_answers(tmp_path):
    client = TestClient(WebClient(app, tmp_path / "missing"))
    assert client.get("/healthz", headers=_PAGE).json() == {"status": "ok"}
    assert client.get("/series/12", headers=_PAGE).status_code == 401


def test_the_schema_documents_the_api_under_api():
    schema = TestClient(app).get("/api/openapi.json").json()
    paths = set(schema["paths"])
    assert "/api/auth/login" in paths and "/api/series/{series_id}" in paths
    assert "/opds/" in paths and "/kosync/users/auth" in paths
    assert not {p for p in paths if p.startswith(("/series", "/books", "/auth", "/me"))}
    ids = Counter(op["operationId"] for item in schema["paths"].values() for op in item.values() if "operationId" in op)
    assert [i for i, n in ids.items() if n > 1] == []
    assert TestClient(app).get("/series/12").status_code == 401  # v1's address still answers
