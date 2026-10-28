"""AI-powered "För dig" recommendations + swipe discovery — see app/ai/
recommendations.py for the generation/dedup logic. AI-generated
collections live in collections.py's own POST /admin/collections/generate
(admin-only, alongside the rest of collection management) rather than
here, to keep this router scoped to the per-user recommendation feed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai.base import AIProviderError
from app.ai.recommendations import generate_recommendations_for_user
from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.ai_recommendation import AIRecommendation
from app.models.enums import AISuggestionStatus, RequestMediaType
from app.models.request import Request
from app.models.user import User
from app.schemas.ai import AIRecommendationOut, AISwipeIn
from kodex.delivery.notify import notify_new_request

router = APIRouter(prefix="/ai", tags=["ai"])


def _get_suggestion_or_404(recommendation_id: int, db: Session, user: User) -> AIRecommendation:
    suggestion = db.get(AIRecommendation, recommendation_id)
    if suggestion is None or suggestion.user_id != user.id:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return suggestion


@router.get("/recommendations", response_model=list[AIRecommendationOut])
def list_recommendations(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[AIRecommendation]:
    """The current cached batch — see recommendations.py's docstring for
    why generating a fresh one is a separate, explicit action rather than
    happening automatically on every page load (cost + latency).
    """
    return (
        db.query(AIRecommendation)
        .filter(AIRecommendation.user_id == user.id, AIRecommendation.status == AISuggestionStatus.SUGGESTED)
        .order_by(AIRecommendation.created_at.desc())
        .all()
    )


@router.post("/recommendations/generate", response_model=list[AIRecommendationOut])
def generate_recommendations(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[AIRecommendation]:
    settings = get_settings()
    if not settings.ai_provider or not settings.ai_api_key:
        raise HTTPException(status_code=400, detail="AI-rekommendationer är inte konfigurerat än")
    try:
        return generate_recommendations_for_user(db, user, settings)
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/recommendations/{recommendation_id}/swipe", response_model=AIRecommendationOut)
def swipe_recommendation(
    recommendation_id: int, payload: AISwipeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AIRecommendation:
    suggestion = _get_suggestion_or_404(recommendation_id, db, user)
    if suggestion.status != AISuggestionStatus.SUGGESTED:
        raise HTTPException(status_code=409, detail="Recommendation was already swiped")

    if payload.direction == "left":
        suggestion.status = AISuggestionStatus.DISMISSED
        db.add(suggestion)
        db.commit()
        db.refresh(suggestion)
        return suggestion

    # "right" — becomes a real Request, same queue/notification path as an
    # ordinary user-submitted one (see requests.py's create_request);
    # falls back to SERIES when the LLM didn't give a usable media_type
    # guess, Kodex's most common library type.
    request = Request(
        requested_by_user_id=user.id,
        title=suggestion.title,
        media_type=suggestion.media_type_guess or RequestMediaType.SERIES,
    )
    db.add(request)
    db.flush()

    suggestion.status = AISuggestionStatus.REQUESTED
    suggestion.request_id = request.id
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)

    notify_new_request(request, settings=get_settings())

    return suggestion
