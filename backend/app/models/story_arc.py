from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.collection import Collection


class StoryArc(Base):
    """A story arc/event — the authoritative side of Uppdrag 7 Del D's
    missing-issue feature. Distinct from the auto-created smart Collection
    with the same name (see engine.py's _ensure_arc_collections and
    kodex/collections/rules.py): the Collection is "every book we already
    own tagged with this arc name" (cheap, always available, drives the
    normal browsing view); this table is "the arc's full issue roster
    according to its source provider" (expensive — several API calls, see
    app/enrichment/story_arc_roster.py (Comic Vine) and metron.py (Metron)
    — only fetched on demand when an admin actually wants to see what's
    missing).

    Exactly one of comicvine_id/metron_id/cbl_path/locg_event_id is set,
    identifying which provider (and roster-fetch function) owns this row
    — see refresh_story_arc_task in app/workers/tasks.py for the branch.
    Added metron_id 2026-09-11 alongside the Metron integration: Metron is
    tried first for a newly-discovered arc (better-curated story-arc data
    than Comic Vine's own sparse story_arc_credits — see metron.py), with
    Comic Vine used as the fallback when Metron has nothing for a given
    issue. Added cbl_path the same day, alongside CBL-ReadingLists (see
    app/enrichment/cbl.py) — unlike the other two, a CBL-sourced row is
    never created automatically (there's no per-issue reverse lookup in
    that format); it only ever comes from an admin explicitly searching
    and linking one via app/api/routes/cbl.py. Added locg_event_id
    2026-09-22 alongside League of Comic Geeks (see
    app/enrichment/leagueofcomicgeeks.py) — same admin paste-a-link flow
    as CBL, not automatic, for the same reason. All four id columns stay
    nullable rather than one required — a row from any one source may
    have no known equivalent on the others.
    """

    __tablename__ = "story_arcs"

    id: Mapped[int] = mapped_column(primary_key=True)
    comicvine_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    metron_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    # The repo-relative file path (e.g. "DC/Events/.../Knightfall Saga.cbl")
    # of the linked CBL-ReadingLists file — its own natural, stable
    # identifier, there being no numeric id in that format.
    cbl_path: Mapped[str | None] = mapped_column(String(1024), unique=True, nullable=True)
    # League of Comic Geeks' own numeric event id (from a pasted event URL
    # — see app/api/routes/leagueofcomicgeeks.py). No natural string key
    # like CBL's path, so this mirrors comicvine_id/metron_id instead.
    locg_event_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(500))
    # Best-effort synopsis — CBL itself has no description field (see
    # cbl.py's link() route), so this is filled in via a Comic Vine
    # story-arc name search at link time when a plausible match is found.
    # Null for Comic Vine/Metron-sourced rows for now (those already show
    # a generic description on the collection page — see
    # (protected)/collections/[id]/page.tsx).
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The matching auto-created smart Collection, if one exists yet (it's
    # created the first time ANY owned book is tagged with this arc name —
    # see engine.py — which normally happens before anyone would think to
    # fetch this arc's full roster, but nullable defensively in case the
    # roster is ever fetched a different way in the future).
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id", ondelete="SET NULL"), nullable=True)

    # Null until the roster has actually been fetched at least once (see
    # roster_stale in app/api/routes/collections.py for how this drives
    # the frontend's "hämta/uppdatera platshållare"-knapp).
    roster_fetched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    collection: Mapped[Collection | None] = relationship()
    issues: Mapped[list[StoryArcIssue]] = relationship(
        back_populates="story_arc", cascade="all, delete-orphan", order_by="StoryArcIssue.order_index"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StoryArc id={self.id} name={self.name!r}>"


class StoryArcIssue(Base):
    """One issue in a StoryArc's roster, in Comic Vine's reading order
    (order_index, derived from cover_date at fetch time — see
    app/enrichment/story_arc_roster.py). book_id is set once/if we
    recognize an owned Book as this exact issue (matched by
    comicvine_issue_id against BookMetadata.external_ids) — null means
    "Comic Vine says this belongs in the arc, we don't have it": the
    "Saknas" placeholder case.
    """

    __tablename__ = "story_arc_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    story_arc_id: Mapped[int] = mapped_column(ForeignKey("story_arcs.id", ondelete="CASCADE"))
    comicvine_issue_id: Mapped[int] = mapped_column(Integer)
    order_index: Mapped[int] = mapped_column(Integer)

    display_name: Mapped[str] = mapped_column(String(500))
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    site_detail_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id", ondelete="SET NULL"), nullable=True)

    story_arc: Mapped[StoryArc] = relationship(back_populates="issues")
    book: Mapped[Book | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StoryArcIssue id={self.id} display_name={self.display_name!r} book_id={self.book_id}>"
