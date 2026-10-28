from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from app.models.enums import LibraryType, SortingStatus


class SortingItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_path: str
    detected_type: LibraryType | None
    detected_reason: str
    resolved_type: LibraryType | None
    status: SortingStatus
    created_at: dt.datetime
    resolved_at: dt.datetime | None
    applied_at: dt.datetime | None
    apply_error: str | None


class SortingResolve(BaseModel):
    resolved_type: LibraryType
