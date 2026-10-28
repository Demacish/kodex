"""Ties the providers together: picks a provider per book, runs automatic
enrichment (fill-blanks-only), and applies a user-confirmed manual match
(overwrite, then lock the row against future automatic changes).
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.enrichment import anilist, comicvine, google_books, metron, open_library
from app.enrichment.base import Candidate, EnrichmentResult, is_thin
from app.enrichment.covers import download_cover
from app.models.book import Book
from app.models.collection import Collection
from app.models.enums import PAGE_BASED_FORMATS, CollectionType, LibraryType, MetadataSource
from app.models.metadata import BookMetadata
from app.models.series import Series
from app.models.story_arc import StoryArc
from kodex.acquire.sorting.comicinfo_writer import parse_series_and_number

logger = logging.getLogger(__name__)

PROVIDERS = ("comicvine", "anilist", "open_library", "google_books")

# The fields a manual match's granular "keep vs replace" choice (B8) can
# select between — every field _apply_result's maybe_set/title/cover_path
# handling actually touches. Deliberately excludes external_ids: that's
# identity data (which volume/issue this book IS), not descriptive
# content to selectively keep or replace, so it always merges regardless
# of `only_fields` — same as it already does regardless of `overwrite`.
SELECTABLE_MATCH_FIELDS = frozenset(
    {"title", "authors", "genres", "summary", "publisher", "published_year", "language", "story_arcs", "cover_path"}
)


def _search_query_and_number(book: Book) -> tuple[str, float | None]:
    """A clean series name (+ parsed issue number, if the filename had
    one) to search a provider with — NOT book.series.title, which before
    a Comic Vine match is just the raw scene-release folder name
    ("Batman 001 (2016) (Digital) (Zone-Empire)"). Searching Comic Vine
    with that whole string instead of "Batman" gave poor/no matches — reuses the same folder-name parser
    kodex/acquire/sorting/ already has for exactly this "messy name -> series +
    number" problem (see its own docstring for the heuristics).
    """
    # Ebook folders are usually just a filesystem-safe slug of the title
    # (no spaces/punctuation — e.g. "lanternpocketref" for "Lantern Pocket
    # Reference"), unlike comics' scene-release folder names, which
    # really do encode a clean series name (+ issue number) the sorting
    # parser below is built to extract. Trusting the folder name for an
    # ebook produced search queries so mangled that Open Library/Google
    # Books consistently found zero matches — found 2026-09-21 after a
    # library-wide enrich matched 0/131 ebooks. The embedded metadata
    # title (from the EPUB/PDF's own metadata, not the folder name) is
    # the reliable source for this library type, so it takes priority.
    if book.library.library_type == LibraryType.EBOOKS and book.book_metadata is not None and book.book_metadata.title:
        return book.book_metadata.title, None

    folder_name = Path(book.file_path).parts[0] if book.file_path else ""
    if folder_name:
        series_name, number, _year = parse_series_and_number(folder_name)
        if series_name:
            return series_name, number

    if book.series is not None and book.series.title:
        return book.series.title, None
    if book.book_metadata is not None and book.book_metadata.title:
        return book.book_metadata.title, None
    return Path(book.file_path).stem, None


def provider_for_book(book: Book) -> str:
    """Which provider a book should be matched against, based on its
    library's type. A MIXED library falls back to guessing from the file
    format instead.
    """
    library_type = book.library.library_type
    if library_type == LibraryType.COMICS:
        return "comicvine"
    if library_type == LibraryType.MANGA:
        return "anilist"
    if library_type == LibraryType.EBOOKS:
        return "open_library"

    if book.file_format in PAGE_BASED_FORMATS:
        return "comicvine"
    return "open_library"


def search_provider(
    provider: str,
    query: str,
    *,
    api_key: str = "",
    google_books_api_key: str = "",
) -> list[Candidate]:
    """Used directly by the manual-match API endpoint so a user can search
    a specific provider when automatic matching found nothing (or found
    the wrong thing).
    """
    if provider == "comicvine":
        return comicvine.search(query, api_key) if api_key else []
    if provider == "anilist":
        return anilist.search(query)
    if provider == "open_library":
        return open_library.search(query)
    if provider == "google_books":
        return google_books.search(query, google_books_api_key)
    raise ValueError(f"Unknown enrichment provider: {provider}")


def fetch_details(
    provider: str,
    external_id: str,
    *,
    api_key: str = "",
    google_books_api_key: str = "",
    issue_number: float | None = None,
) -> EnrichmentResult | None:
    if provider == "comicvine":
        return comicvine.fetch_details(external_id, api_key, issue_number=issue_number) if api_key else None
    if provider == "anilist":
        return anilist.fetch_details(external_id)
    if provider == "open_library":
        return open_library.fetch_details(external_id)
    if provider == "google_books":
        return google_books.fetch_details(external_id, google_books_api_key)
    raise ValueError(f"Unknown enrichment provider: {provider}")


def list_issues_for_volume(provider: str, volume_id: str, api_key: str) -> list[Candidate]:
    """The issue-picker step of manual matching (F) — only comicvine has a
    volume/issue split at all (AniList/Open Library/Google Books each
    match one "thing" directly), so this is comicvine-only; the API route
    rejects any other provider before calling in.
    """
    if provider != "comicvine":
        raise ValueError(f"Issue-level matching isn't supported for provider {provider!r}")
    if not api_key:
        return []
    return comicvine.list_issues(volume_id, api_key)


def _apply_result(
    db: Session,
    book: Book,
    result: EnrichmentResult,
    *,
    overwrite: bool,
    source: MetadataSource,
    only_fields: set[str] | None = None,
) -> bool:
    """Merge an EnrichmentResult into book.book_metadata.

    overwrite=False (the automatic path): only fields that are currently
    empty get filled in — embedded metadata and anything already enriched
    keeps priority.
    overwrite=True (a user-confirmed manual match): the provider's data
    wins for every field it returned, since the user just told us this is
    the correct match.

    only_fields (B8, manual matches only — auto_enrich_book never passes
    it): when given, further restricts which of SELECTABLE_MATCH_FIELDS
    actually get touched, letting a user keep e.g. their own summary while
    still accepting the match's authors/cover. None (the default)
    preserves the original all-or-nothing behavior. external_ids is
    deliberately NOT gated by this — see SELECTABLE_MATCH_FIELDS.
    """
    meta = book.book_metadata
    if meta is None:
        meta = BookMetadata(
            book_id=book.id,
            title=result.title or Path(book.file_path).stem,
            sort_title=result.title or "",
            source=source,
        )
        book.book_metadata = meta

    changed = False

    locked = set(meta.locked_fields or [])

    def field_selected(attr: str) -> bool:
        return (only_fields is None or attr in only_fields) and (only_fields is not None or attr not in locked)

    def maybe_set(attr: str, value) -> None:
        nonlocal changed
        if value in (None, "", []) or not field_selected(attr):
            return
        current = getattr(meta, attr)
        if (overwrite or not current) and current != value:
            setattr(meta, attr, value)
            changed = True

    # Title is deliberately NOT behind the overwrite=False "only fill in
    # if empty" rule the other fields use below. meta.title is never
    # actually empty by the time enrichment runs — the scanner always
    # seeds it with the raw filename as a fallback (see scanner.py's
    # _build_metadata_fields), and stamps source=EMBEDDED whether that
    # came from a real ComicInfo.xml <Title> or was just the filename —
    # there's no way to tell the two apart here. With the old "only if
    # empty" rule, that meant a confident Comic Vine issue match NEVER
    # replaced a scene-release filename ("Absolute Skyrider 001 (2025)
    # (Webrip) (The Quiet Archivist-DCP)") with the real issue title,
    # across nearly this whole library. A row already matched by the user
    # (source=MANUAL) never reaches this function in the first place —
    # auto_enrich_book returns early for those — so this can't clobber a
    # deliberate user edit.
    if result.title and meta.title != result.title and field_selected("title"):
        meta.title = result.title
        meta.sort_title = result.title
        changed = True

    maybe_set("authors", result.authors)
    maybe_set("genres", result.genres)
    maybe_set("summary", result.summary)
    maybe_set("publisher", result.publisher)
    maybe_set("published_year", result.published_year)
    maybe_set("language", result.language)
    maybe_set("story_arcs", result.story_arcs)

    if result.cover_url and (overwrite or not meta.cover_path) and field_selected("cover_path"):
        cover_path = download_cover(result.cover_url, book.id)
        if cover_path:
            meta.cover_path = cover_path
            book.cover_key = None  # the generated sizes come from the new cover
            changed = True

    if result.external_ids:
        meta.external_ids = {**(meta.external_ids or {}), **result.external_ids}
        changed = True

    if changed:
        meta.source = source
        meta.enriched_at = dt.datetime.now(dt.UTC)
        db.add(meta)
        db.flush()

    return changed


def _resolve_story_arcs(result: EnrichmentResult, metron_username: str, metron_password: str) -> str:
    """Tries Metron for this (already Comic-Vine-matched) issue's story
    arcs, overwriting result.story_arcs/story_arc_ids in place with
    Metron's version when it finds any — falling back to whatever Comic
    Vine's own (usually sparser) story_arc_credits already put there
    otherwise. Returns which provider's ids ended up on the result
    ("metron" or "comicvine"), needed by _ensure_arc_collections to know
    which StoryArc column to key on. A no-op (always "comicvine") when
    Metron credentials are unset or this book didn't come from Comic Vine
    at all — see metron.py's own docstring for the full rationale.
    """
    comicvine_issue_id = result.external_ids.get("comicvine_issue_id")
    if not metron_username or not metron_password or not comicvine_issue_id:
        return "comicvine"

    try:
        metron_arcs = metron.fetch_arcs_for_comicvine_issue(comicvine_issue_id, metron_username, metron_password)
    except Exception:
        logger.exception("Metron arc lookup failed for Comic Vine issue %s", comicvine_issue_id)
        return "comicvine"

    if not metron_arcs:
        return "comicvine"

    result.story_arcs = [name for _id, name in metron_arcs]
    result.story_arc_ids = {name: metron_id for metron_id, name in metron_arcs}
    return "metron"


def auto_enrich_book(
    db: Session,
    book: Book,
    *,
    comicvine_api_key: str = "",
    google_books_api_key: str = "",
    metron_username: str = "",
    metron_password: str = "",
    force: bool = False,
) -> bool:
    """Automatic, best-guess enrichment. Skips a book already matched to a
    provider whose metadata isn't thin (unless force=True) and never
    touches a MANUAL row — a user's confirmed match (or future hand-edit)
    is permanent until they change it themselves. Returns True if anything
    changed.

    is_thin() alone used to gate this (any not-yet-matched EMBEDDED row
    included) — found 2026-09-11 to be silently blocking most of the
    library: the scanner's own ComicInfo.xml/filename parsing fills in
    published_year (one of THINNESS_FIELDS) for the vast majority of
    scene-release-style folder names ("Batman 002 (2016)
    ..."), which made is_thin() return False before this book had ever
    been matched to Comic Vine at all — so it was never even attempted.
    123 of 130 never-matched books in the comics library were stuck this
    way, which is also why Uppdrag 7 Del A's canonical-series grouping and
    Del D's story-arc collections looked broken (they only ever fire on a
    successful match — see below). Only skip the is_thin() case for a row
    that's already gone through a successful provider match (source ==
    ENRICHED) — an EMBEDDED row hasn't, regardless of how many fields the
    scanner happened to fill in, so it must always get a real attempt.
    """
    meta = book.book_metadata
    if meta is not None and meta.source == MetadataSource.MANUAL:
        return False
    if meta is not None and not force and meta.source == MetadataSource.ENRICHED and not is_thin(meta):
        return False

    # The matching engine (kodex.matching) owns which series and issue a
    # book is. Once it has decided, only the issue's details are filled
    # in here: no new search, no regrouping.
    series = book.series
    issue_id = (meta.external_ids or {}).get("comicvine_issue_id") if meta is not None else None
    if series is not None and series.match_status in ("auto", "manual"):
        if not issue_id or not comicvine_api_key:
            return False
        try:
            result = comicvine.fetch_issue_details(str(issue_id), comicvine_api_key)
        except Exception:
            logger.exception("Issue details failed for book %s (issue %s)", book.id, issue_id)
            return False
        if result is None:
            return False
        result.external_ids = {}  # identity stays the engine's
        return _apply_result(db, book, result, overwrite=False, source=MetadataSource.ENRICHED)

    provider = provider_for_book(book)
    query, parsed_number = _search_query_and_number(book)
    issue_number = book.number if book.number is not None else parsed_number

    try:
        if provider == "comicvine":
            if not comicvine_api_key:
                logger.info("Skipping Comic Vine enrichment for book %s: no API key configured", book.id)
                return False
            result = comicvine.auto_match(query, issue_number, comicvine_api_key)
        elif provider == "anilist":
            result = anilist.auto_match(query)
        elif provider == "open_library":
            isbn = meta.isbn if meta else None
            result = open_library.auto_match(query, isbn) or google_books.auto_match(query, google_books_api_key)
        else:
            result = None
    except Exception:
        logger.exception("Enrichment failed for book %s (provider=%s, query=%r)", book.id, provider, query)
        return False

    if result is None:
        logger.info(
            "No automatic enrichment match for book %s (%r) via %s — try a manual match instead",
            book.id,
            query,
            provider,
        )
        return False

    arc_provider = _resolve_story_arcs(result, metron_username, metron_password)
    changed = _apply_result(db, book, result, overwrite=False, source=MetadataSource.ENRICHED)
    if changed:
        _reparent_to_canonical_series(db, book, result)
        _ensure_arc_collections(db, result.story_arcs, result.story_arc_ids, arc_provider)
    return changed


def _fetch_match_result(
    book: Book, provider: str, external_id: str, *, is_issue: bool, comicvine_api_key: str, google_books_api_key: str
) -> EnrichmentResult | None:
    """The "resolve a picked external_id into full details" step shared by
    apply_manual_match and preview_manual_match (B8) — kept as one place
    so a preview can never drift from what actually applying would fetch.
    """
    if is_issue:
        return comicvine.fetch_issue_details(external_id, api_key=comicvine_api_key)
    return fetch_details(
        provider,
        external_id,
        api_key=comicvine_api_key,
        google_books_api_key=google_books_api_key,
        issue_number=book.number,
    )


def compute_field_diff(book: Book, result: EnrichmentResult) -> dict[str, dict[str, object]]:
    """B8: a side-effect-free {field: {"current", "incoming"}} diff for
    every SELECTABLE_MATCH_FIELDS entry the match result actually offers
    a (non-empty) value for — powers GET .../enrichment/preview so a user
    can see what a match would change before choosing which fields to
    keep vs replace, without it actually touching the database.
    """
    meta = book.book_metadata
    incoming_by_field = {
        "title": result.title,
        "authors": result.authors,
        "genres": result.genres,
        "summary": result.summary,
        "publisher": result.publisher,
        "published_year": result.published_year,
        "language": result.language,
        "story_arcs": result.story_arcs,
        # download_cover() is a real HTTP fetch + disk write — a preview
        # only shows the source URL, never fetches it, so "reject this
        # field" costs nothing and "accept it" still downloads fresh at
        # actual apply time.
        "cover_path": result.cover_url,
    }
    diff: dict[str, dict[str, object]] = {}
    for field in SELECTABLE_MATCH_FIELDS:
        incoming = incoming_by_field.get(field)
        if incoming in (None, "", []):
            continue
        # "current" reported as the (source) cover_path for the
        # cover_path field, in keeping with incoming being cover_url
        # rather than an already-downloaded path — both are just "what's
        # there now" vs "what a fetch would replace it with" for display.
        diff[field] = {"current": getattr(meta, field, None), "incoming": incoming}
    return diff


def apply_manual_match(
    db: Session,
    book: Book,
    provider: str,
    external_id: str,
    *,
    is_issue: bool = False,
    fields: set[str] | None = None,
    comicvine_api_key: str = "",
    google_books_api_key: str = "",
    metron_username: str = "",
    metron_password: str = "",
) -> bool:
    """A user explicitly picked `external_id` from search_provider() (a
    volume/series) or list_issues_for_volume() (a specific issue, F)
    results for this book — used when automatic matching found nothing,
    found the wrong series, or (issue-level) guessed the wrong issue
    within an otherwise-correct series. Fetches full details and
    overwrites metadata with it, then marks the row MANUAL so it's
    protected from future automatic re-enrichment.

    is_issue=True means `external_id` is a Comic Vine issue id, not a
    volume id — only meaningful for the comicvine provider (the only one
    with a volume/issue split at all, see comicvine.py's own docstring);
    rejected by the caller for any other provider.

    fields (B8): None (the default) keeps the original all-or-nothing
    overwrite; a set restricts which SELECTABLE_MATCH_FIELDS actually get
    replaced — see _apply_result's only_fields.
    """
    result = _fetch_match_result(
        book,
        provider,
        external_id,
        is_issue=is_issue,
        comicvine_api_key=comicvine_api_key,
        google_books_api_key=google_books_api_key,
    )
    if result is None:
        return False
    arc_provider = _resolve_story_arcs(result, metron_username, metron_password)
    changed = _apply_result(db, book, result, overwrite=True, source=MetadataSource.MANUAL, only_fields=fields)
    if changed:
        _reparent_to_canonical_series(db, book, result)
        _ensure_arc_collections(db, result.story_arcs, result.story_arc_ids, arc_provider)
    return changed


def preview_manual_match(
    book: Book,
    provider: str,
    external_id: str,
    *,
    is_issue: bool = False,
    comicvine_api_key: str = "",
    google_books_api_key: str = "",
) -> dict[str, dict[str, object]] | None:
    """B8: fetches the same details apply_manual_match would, but only
    returns the field-by-field diff (compute_field_diff) — no database
    write, no story-arc resolution, no reparenting. None means the
    provider had nothing for this external_id, same as apply_manual_match
    returning False for that reason.
    """
    result = _fetch_match_result(
        book,
        provider,
        external_id,
        is_issue=is_issue,
        comicvine_api_key=comicvine_api_key,
        google_books_api_key=google_books_api_key,
    )
    if result is None:
        return None
    return compute_field_diff(book, result)


def _reparent_to_canonical_series(db: Session, book: Book, result: EnrichmentResult) -> None:
    """Moves a book into a single canonical Series row per Comic Vine
    volume_id (creating one, or promoting the book's current folder-based
    row to canonical, the first time any book from that volume matches)
    instead of leaving it under scanner.py's one-folder-one-series
    default. See Series.comicvine_volume_id's own docstring for why.

    For every other provider (AniList/Open Library/Google Books don't set
    comicvine_volume_id) this instead just keeps a *solo* series (the
    common ebook case - one folder/series per book) in sync with the
    book's own newly matched title, which scanner.py's one-folder-one-
    series default otherwise leaves stuck on the raw folder name forever
    - confirmed 2026-09-17 this was also why re-matching a book auto-
    searched with that stale series title as its query and found nothing.
    Left alone for a multi-book series (AniList volumes, a manga series
    scanned as one folder) since there's no single "the" title to adopt.
    """
    volume_id = result.external_ids.get("comicvine_volume_id")
    if volume_id is None:
        series = book.series
        if series is not None and result.title and series.title != result.title:
            book_count = db.query(Book).filter(Book.series_id == series.id).count()
            if book_count == 1:
                series.title = result.title
                series.sort_title = result.title
                db.add(series)
        return

    old_series = book.series
    canonical = (
        db.query(Series)
        .filter(Series.library_id == book.library_id, Series.comicvine_volume_id == volume_id)
        .one_or_none()
    )

    if canonical is None:
        if old_series is not None and old_series.comicvine_volume_id is None:
            # First book from this volume to match, and its current
            # folder-row isn't already claimed by a *different* volume —
            # promote it to canonical rather than creating a new row.
            canonical = old_series
            canonical.comicvine_volume_id = volume_id
        else:
            fallback_title = result.series_title or (old_series.title if old_series else book.file_path)
            canonical = Series(
                library_id=book.library_id,
                title=fallback_title,
                sort_title=fallback_title,
                path=old_series.path if old_series else "",
                comicvine_volume_id=volume_id,
            )
            db.add(canonical)

    if result.series_title and canonical.title != result.series_title:
        canonical.title = result.series_title
        canonical.sort_title = result.series_title
    db.add(canonical)
    db.flush()

    if old_series is not None and old_series.id == canonical.id:
        return

    book.series_id = canonical.id
    db.add(book)
    db.flush()

    if old_series is not None:
        remaining = db.query(Book).filter(Book.series_id == old_series.id).count()
        if remaining == 0:
            db.delete(old_series)


def _ensure_arc_collections(db: Session, arc_names: list[str], arc_ids: dict[str, int], provider: str) -> None:
    """Auto-creates a smart Collection (rule: {"field": "story_arcs",
    "value": arc_name}) for every crossover/event arc name a just-matched
    book belongs to, if one doesn't already exist — the "utan manuellt
    adminsteg" requirement: an admin never has to notice a new arc exists
    and set up a collection for it by hand, it just appears once the first
    book from it gets matched. Idempotent (checked by exact name+rule, not
    just name, in case a same-named smart collection was ever hand-created
    with a different rule) — safe to call on every enrichment run, not
    just the first time an arc is seen. owner_user_id left null: like
    every other shared catalog table in this single-household app (see
    Series's own note on the same design choice), not a personal list.

    Also upserts a StoryArc row (comicvine_id OR metron_id, per `provider`
    — see _resolve_story_arcs — + link to the Collection) for every name
    arc_ids has an id for. This is what app/enrichment/story_arc_roster.py
    (Comic Vine) / metron.py (Metron)'s "fetch the full roster, show
    what's missing" feature (Uppdrag 7 Del D) needs to know WHICH arc, on
    WHICH provider, to ask about; arc_names alone (just text) isn't
    enough for that, only for the Collection-filtering above.
    """
    story_arc_id_column = StoryArc.metron_id if provider == "metron" else StoryArc.comicvine_id

    for arc_name in arc_names:
        rule = {"field": "story_arcs", "value": arc_name}
        collection = (
            db.query(Collection)
            .filter(Collection.name == arc_name, Collection.collection_type == CollectionType.SMART)
            .filter(Collection.rule.op("->>")("value") == arc_name)
            .one_or_none()
        )
        if collection is None:
            collection = Collection(name=arc_name, collection_type=CollectionType.SMART, rule=rule, owner_user_id=None)
            db.add(collection)
            db.flush()

        provider_arc_id = arc_ids.get(arc_name)
        if provider_arc_id is None:
            continue
        story_arc = db.query(StoryArc).filter(story_arc_id_column == provider_arc_id).one_or_none()
        if story_arc is None:
            kwargs = {"metron_id": provider_arc_id} if provider == "metron" else {"comicvine_id": provider_arc_id}
            db.add(StoryArc(name=arc_name, collection_id=collection.id, **kwargs))
        elif story_arc.collection_id is None:
            story_arc.collection_id = collection.id
            db.add(story_arc)

    if arc_names:
        db.flush()
