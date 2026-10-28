from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel

ReleaseEventStatus = Literal["unreleased", "released", "owned"]


class ReleaseEventOut(BaseModel):
    id: int
    series_id: int
    series_title: str
    external_issue_id: str
    provider: str
    issue_number: str | None
    title: str | None
    store_date: dt.date | None
    cover_date: dt.date | None
    owned_book_id: int | None
    dismissed: bool
    # Computed at read time (see api/routes/releases.py's _status), never
    # stored — see SeriesReleaseEvent's own docstring for why.
    status: ReleaseEventStatus
