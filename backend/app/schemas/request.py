from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.enums import RequestMediaType, RequestStatus


class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requested_by_user_id: int
    # Shown in the admin queue so an admin doesn't have to cross-reference
    # a user id — derived from the requested_by relationship, not a column
    # on Request itself.
    requested_by_username: str
    title: str
    media_type: RequestMediaType
    external_link: str | None
    status: RequestStatus
    admin_note: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    # Set only for requests created via the "Begär saknade nummer" bulk
    # action — see collections.py's request_missing_issues. Lets the
    # admin queue show/filter/export "which collection did this come
    # from" (2026-09-11).
    collection_id: int | None
    collection_name: str | None
    # Batch-C tie-in — see app/models/request.py's own docstrings.
    auto_download_enabled: bool
    download_id: int | None
    series_id: int | None = None
    issue_number: float | None = None
    # The download's state, while there is one (queued, downloading, completed, failed, needs_review).
    download_status: str | None = None


class RequestCreate(BaseModel):
    title: str = ""
    media_type: RequestMediaType
    external_link: str | None = None
    # A missing issue of a series in the library (kodex.acquire); the
    # title may then be left empty ("<series> #<number>").
    series_id: int | None = None
    issue_number: float | None = None

    @model_validator(mode="after")
    def _check_title(self) -> RequestCreate:
        if (self.series_id is None) != (self.issue_number is None):
            raise ValueError("series_id and issue_number go together")
        if not self.title.strip() and self.series_id is None:
            raise ValueError("title must not be empty")
        return self


class RequestUpdate(BaseModel):
    # Both optional and independent — an admin can update either without
    # touching the other (e.g. add a note without changing status yet).
    status: RequestStatus | None = None
    admin_note: str | None = None


class RequestAutoDownloadIn(BaseModel):
    """POST /requests/{id}/auto-download — an admin's opt-in attempt at an
    automatic download (see app/models/request.py's auto_download_enabled
    docstring). `library_id` is required here rather than stored on
    Request itself — a Request has no notion of a target library until
    an admin picks one for this specific download attempt.
    """

    library_id: int
