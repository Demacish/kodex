from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class StoryArcIssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_index: int
    display_name: str
    cover_url: str | None
    site_detail_url: str | None
    book_id: int | None


class StoryArcOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    comicvine_id: int | None
    metron_id: int | None
    cbl_path: str | None
    locg_event_id: int | None
    name: str
    description: str | None
    collection_id: int | None
    roster_fetched_at: dt.datetime | None
    issues: list[StoryArcIssueOut]


class StoryArcImportIn(BaseModel):
    """C15 — POST /collections/story-arc-import. `name` is optional: left
    out, the route fetches the arc's own name from Comic Vine first (see
    app/enrichment/story_arc_roster.py's fetch_arc_name); given, it skips
    that lookup (also the fallback when the lookup itself fails).
    """

    comicvine_story_arc_id: int
    name: str | None = None


class StoryArcImportOut(BaseModel):
    collection_id: int
    job_id: str
