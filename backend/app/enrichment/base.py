"""Shared types for enrichment providers (Comic Vine, AniList, Open Library,
Google Books). Each provider returns an EnrichmentResult; the engine
(app/enrichment/engine.py) is what decides which fields actually get
written to BookMetadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Candidate:
    """One search result shown to a user picking a manual match — kept
    deliberately small (no description text) since it's just for choosing
    between a handful of options, not for display as final metadata.
    """

    external_id: str
    title: str
    year: int | None = None
    thumbnail_url: str | None = None
    # Free-text shown alongside the title to help disambiguate, e.g. an
    # issue count ("112 nummer") or an author name.
    subtitle: str | None = None
    # Issue count, when the provider has one (Comic Vine volumes) — used to
    # break ties in best_match() when several candidates share the exact
    # same name (e.g. a publisher lists both the ongoing series and its
    # own collected-editions line under the identical title "Absolute
    # Batman"; the one with far more issues is virtually always the
    # ongoing series a single-issue book file should match against).
    issue_count: int | None = None


@dataclass
class EnrichmentResult:
    # The SERIES/volume name — distinct from `title` below, which for a
    # matched individual issue is the issue's own (often blank) title, not
    # the series it belongs to. Used by engine.py to group books under a
    # canonical Series row (Series.comicvine_volume_id) instead of one per
    # scene-release-tagged folder name. Providers that don't distinguish
    # (AniList, Open Library, Google Books — one "thing" per match, no
    # separate series/issue split) just leave this unset.
    series_title: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    # Crossover/event arc name(s) this issue belongs to, from Comic Vine's
    # own story_arc_credits — same field BookMetadata already had for
    # embedded ComicInfo.xml <StoryArc> data (see kodex/collections/rules.py
    # for why this exists at all: a smart collection filtering on this
    # groups books across series automatically, no manual arc-management
    # UI needed). Comic Vine doesn't give a per-issue position *within*
    # the arc the way ComicInfo.xml's <StoryArcNumber> does, so there's no
    # story_arc_numbers here — an arc built from this source sorts by
    # published date instead (see engine.py's auto-collection creation).
    story_arcs: list[str] = field(default_factory=list)
    # name -> Comic Vine story-arc id, for the subset of story_arcs above
    # a provider can actually give an id for (only comicvine.py does).
    # Used by app/enrichment/story_arc_roster.py to fetch an arc's full
    # issue list from Comic Vine directly (Uppdrag 7 Del D's "vilka
    # nummer säger Comic Vine ska vara med, och vilka saknas" feature) —
    # story_arcs alone (just names) isn't enough for that, only for the
    # existing "collection filtered by this arc name" grouping.
    story_arc_ids: dict[str, int] = field(default_factory=dict)
    summary: str | None = None
    publisher: str | None = None
    published_year: int | None = None
    language: str | None = None
    cover_url: str | None = None
    # Provider-specific id(s) to merge into BookMetadata.external_ids, e.g.
    # {"comicvine_volume_id": 1234}.
    external_ids: dict = field(default_factory=dict)


# Fields considered "thin" when empty — a book missing all of these is a
# good candidate for enrichment. Title is deliberately excluded: the
# filename/embedded title is usually present and fine on its own.
THINNESS_FIELDS = ("summary", "genres", "authors", "publisher", "published_year")


def is_thin(metadata) -> bool:  # metadata: app.models.metadata.BookMetadata
    """True if enough descriptive fields are empty that enrichment is worth
    attempting. Never called for rows whose source is MANUAL — the engine
    checks that separately so a user's own edits are never touched.
    """
    for attr in THINNESS_FIELDS:
        value = getattr(metadata, attr)
        if value:  # non-empty string, non-empty list, or non-zero/None-checked int
            return False
    return True
