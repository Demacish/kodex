from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.enums import CollectionType


class CollectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    collection_type: CollectionType
    rule: dict | None
    owner_user_id: int | None
    # Added for the card-grid Collections page (2026-09-11, modeled after
    # metron.cloud/reading-lists/) — not from_attributes, computed
    # per-request in the route (see collections.py's list_collections),
    # since a smart collection has no book rows of its own to count/cover
    # from directly (see this module's own docstring on Collection).
    book_count: int = 0
    cover_book_id: int | None = None
    # True when a manually uploaded cover exists at GET
    # /collections/{id}/cover (see collections.py) — the raw path is
    # never returned, same reasoning as User.has_opds_token not
    # returning the actual token.
    has_custom_cover: bool = False
    # Only set for the auto-created smart collection behind one story arc
    # (see engine.py's _ensure_arc_collections) — lets the frontend show
    # an arc-specific badge/count instead of the generic one.
    story_arc_id: int | None = None


class CollectionCreate(BaseModel):
    name: str
    collection_type: CollectionType
    # Required (and validated against kodex/collections/rules.py) for smart
    # collections; ignored for manual ones.
    rule: dict | None = None
    # Only meaningful for manual collections — the initial set of books.
    # More can be added later via POST /collections/{id}/books.
    book_ids: list[int] = []
    # False (the default) makes a shared collection everyone can see —
    # the normal case, matching Komga's "smart lists" being a curated,
    # shared thing rather than a private one. True scopes it to the
    # creating admin only.
    personal: bool = False

    @model_validator(mode="after")
    def _check_smart_has_rule(self) -> CollectionCreate:
        if self.collection_type == CollectionType.SMART and not self.rule:
            raise ValueError("Smart collections require a 'rule'")
        if self.collection_type == CollectionType.MANUAL and self.rule:
            raise ValueError("Manual collections don't take a 'rule' — add books via book_ids instead")
        return self


class CollectionUpdate(BaseModel):
    name: str | None = None
    # Only settable for a smart collection; validated the same way as on
    # create.
    rule: dict | None = None
