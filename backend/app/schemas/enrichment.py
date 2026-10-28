from __future__ import annotations

from pydantic import BaseModel


class CandidateOut(BaseModel):
    external_id: str
    title: str
    year: int | None
    thumbnail_url: str | None
    subtitle: str | None
    # Which provider this candidate actually came from - the frontend used
    # to hardcode "comicvine" when applying a match (see ManualMatchDialog.
    # tsx), which silently failed to apply for every non-comicvine book
    # (i.e. every ebook/manga match). Round-tripped back on /apply instead.
    provider: str


class ManualMatchIn(BaseModel):
    provider: str
    external_id: str
    # True means external_id is a Comic Vine issue id (from GET
    # .../volumes/{volume_id}/issues, F's second matching step) rather
    # than a volume id — see engine.py's apply_manual_match.
    is_issue: bool = False
    # B8 — granular keep-vs-replace: None (the default, and what every
    # pre-B8 caller still sends) is the original all-fields overwrite. A
    # list restricts the apply to just those SELECTABLE_MATCH_FIELDS —
    # validated against that exact set in the route, not here, so this
    # schema doesn't need to import the enrichment engine module.
    fields: list[str] | None = None


class EnrichmentActionResult(BaseModel):
    changed: bool


class FieldDiffOut(BaseModel):
    current: object | None
    incoming: object | None
