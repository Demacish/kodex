from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from app.models.enums import PageFlagReason, PageFlagResolution


class PageFlagIn(BaseModel):
    reason: PageFlagReason
    note: str | None = None


class PageFlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    book_id: int
    page_index: int
    reason: PageFlagReason
    note: str | None
    flagged_by_user_id: int | None
    flagged_at: dt.datetime
    resolved: bool
    resolved_action: PageFlagResolution | None
    resolved_at: dt.datetime | None


class PageFlagAdminOut(PageFlagOut):
    # Joined in for the admin inbox (page-flags/page.tsx) so it doesn't
    # need a second round trip per row just to show which book a flag
    # belongs to.
    book_title: str
    flagged_by_username: str | None


class PageFlagResolveIn(BaseModel):
    action: PageFlagResolution
