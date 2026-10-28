"""API-level tests for /ai/recommendations* — GET the cached batch,
POST generate (config-gated, delegates to app/ai/recommendations.py),
POST .../swipe (right → creates a Request and notifies, left → dismiss).
Uses the shared `api` fixture (conftest.py) — dependency-overridden DB/auth,
no real network calls (generate_recommendations_for_user and
notify_new_request are both monkeypatched).
"""

from __future__ import annotations

import app.api.routes.ai as ai_module
from app.config import Settings
from app.models.ai_recommendation import AIRecommendation
from app.models.enums import AISuggestionStatus, RequestMediaType
from app.models.user import User


def _seed_recommendation(
    session_factory, *, user_id: int = 1, status: AISuggestionStatus = AISuggestionStatus.SUGGESTED, **overrides
) -> int:
    db = session_factory()
    if db.get(User, user_id) is None:
        # Another user than the api fixture's own (id 1); foreign keys are
        # enforced, so the row has to exist.
        db.add(User(id=user_id, oidc_subject=f"sub-{user_id}", username=f"user{user_id}"))
        db.flush()
    defaults = dict(user_id=user_id, title="Some Series", author="Some Author", reason="because", status=status)
    defaults.update(overrides)
    row = AIRecommendation(**defaults)
    db.add(row)
    db.commit()
    recommendation_id = row.id
    db.close()
    return recommendation_id


def test_list_recommendations_only_returns_suggested_for_current_user(api):
    client, session_factory = api
    _seed_recommendation(session_factory, status=AISuggestionStatus.SUGGESTED)
    _seed_recommendation(session_factory, status=AISuggestionStatus.DISMISSED)
    _seed_recommendation(session_factory, user_id=999, status=AISuggestionStatus.SUGGESTED)

    response = client.get("/ai/recommendations")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_generate_returns_400_when_not_configured(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(ai_module, "get_settings", lambda: Settings(database_url="sqlite:///:memory:"))

    response = client.post("/ai/recommendations/generate")
    assert response.status_code == 400


def test_generate_delegates_to_recommendations_module(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(
        ai_module,
        "get_settings",
        lambda: Settings(database_url="sqlite:///:memory:", ai_provider="openai", ai_api_key="k"),
    )
    monkeypatch.setattr(ai_module, "generate_recommendations_for_user", lambda db, user, settings: [])

    response = client.post("/ai/recommendations/generate")
    assert response.status_code == 200
    assert response.json() == []


def test_swipe_right_creates_request_and_marks_requested(api, monkeypatch):
    client, session_factory = api
    recommendation_id = _seed_recommendation(session_factory, media_type_guess=RequestMediaType.MANGA)
    notified = []
    monkeypatch.setattr(ai_module, "notify_new_request", lambda request, *, settings: notified.append(request.title))

    response = client.post(f"/ai/recommendations/{recommendation_id}/swipe", json={"direction": "right"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "requested"
    assert body["request_id"] is not None
    assert notified == ["Some Series"]

    db = session_factory()
    from app.models.request import Request

    request = db.get(Request, body["request_id"])
    assert request.title == "Some Series"
    assert request.media_type == RequestMediaType.MANGA
    db.close()


def test_swipe_left_dismisses_without_creating_request(api):
    client, session_factory = api
    recommendation_id = _seed_recommendation(session_factory)

    response = client.post(f"/ai/recommendations/{recommendation_id}/swipe", json={"direction": "left"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dismissed"
    assert body["request_id"] is None


def test_swipe_already_swiped_returns_409(api):
    client, session_factory = api
    recommendation_id = _seed_recommendation(session_factory, status=AISuggestionStatus.DISMISSED)

    response = client.post(f"/ai/recommendations/{recommendation_id}/swipe", json={"direction": "left"})
    assert response.status_code == 409


def test_swipe_unknown_recommendation_returns_404(api):
    client, _ = api
    response = client.post("/ai/recommendations/999999/swipe", json={"direction": "left"})
    assert response.status_code == 404


def test_swipe_another_users_recommendation_returns_404(api):
    client, session_factory = api
    recommendation_id = _seed_recommendation(session_factory, user_id=999)

    response = client.post(f"/ai/recommendations/{recommendation_id}/swipe", json={"direction": "left"})
    assert response.status_code == 404
