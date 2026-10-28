from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.enums import AISuggestionStatus, RequestMediaType


class AIRecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    author: str | None
    reason: str | None
    media_type_guess: RequestMediaType | None
    cover_url: str | None
    status: AISuggestionStatus
    request_id: int | None
    created_at: dt.datetime


class AISwipeIn(BaseModel):
    direction: Literal["right", "left"]


class AICollectionGenerateIn(BaseModel):
    prompt: str
    library_id: int | None = None
    name: str | None = None
