"""Search in PostgreSQL (ADR 0005), in place of Meilisearch.

Books: every word has to appear in the book's title, series, authors,
genres, tags, story arcs or publisher; or the whole query is close to the
title or the series (pg_trgm's word similarity, which forgives typos); or
the summary matches it as a full-text query. Hits rank by how close the
title or series is. Words are matched as substrings, so CJK titles, which
have no spaces, are found too.

Book text (``content_index_entries``, filled per library by the full-text
job): a full-text query with a highlighted snippet.

Full-text search uses the 'simple' configuration, without stemming: the
same for Swedish, English and everything else."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

MAX_WORDS = 8
_START, _STOP = "\x02", "\x03"  # marks ts_headline puts around a hit, before escaping
# The JSON lists read through jsonb, which prints letters as they are
# (json keeps the \u escapes they were stored with).
_HAYSTACK = (
    "lower(concat_ws(' ', m.title, s.title, m.authors::jsonb::text, m.genres::jsonb::text, m.tags::jsonb::text, "
    "m.story_arcs::jsonb::text, m.publisher))"
)


@dataclass(frozen=True)
class BookHit:
    book_id: int
    title: str
    series_id: int | None
    series_title: str | None
    library_id: int
    library_name: str | None
    file_format: str
    cover_path: str | None


@dataclass(frozen=True)
class TextHit:
    book_id: int
    library_id: int
    title: str
    position: str
    snippet: str  # escaped HTML, the hit in <mark>


def _words(query: str) -> list[str]:
    return [w for w in query.lower().split() if w][:MAX_WORDS]


def books(db: Session, query: str, *, library_id: int | None = None, series_id: int | None = None,
          limit: int = 30) -> list[BookHit]:  # fmt: skip
    words = _words(query)
    if not words:
        return []
    params: dict[str, Any] = {"q": " ".join(words), "raw": query, "limit": limit}
    every = " AND ".join(f"strpos({_HAYSTACK}, :w{i}) > 0" for i in range(len(words)))
    params.update({f"w{i}": word for i, word in enumerate(words)})
    scope = ""
    if library_id is not None:
        scope += " AND b.library_id = :library_id"
        params["library_id"] = library_id
    if series_id is not None:
        scope += " AND b.series_id = :series_id"
        params["series_id"] = series_id
    rows = db.execute(
        text(
            "SELECT b.id, coalesce(m.title, b.file_path) AS title, b.series_id, s.title AS series_title, b.library_id,"
            " l.name AS library_name, lower(b.file_format) AS file_format, m.cover_path,"
            " greatest(word_similarity(:q, lower(coalesce(m.title, ''))),"
            "          word_similarity(:q, lower(coalesce(s.title, ''))) * 0.95) AS score"
            " FROM books b JOIN libraries l ON l.id = b.library_id"
            " LEFT JOIN book_metadata m ON m.book_id = b.id LEFT JOIN series s ON s.id = b.series_id"
            " WHERE b.missing_since IS NULL" + scope + " AND ((" + every + ")"
            "  OR :q <% lower(m.title) OR :q <% lower(s.title)"
            "  OR to_tsvector('simple', coalesce(m.summary, '')) @@ websearch_to_tsquery('simple', :raw))"
            " ORDER BY score DESC, s.sort_title NULLS LAST, b.number NULLS LAST, b.id LIMIT :limit"
        ),
        params,
    ).all()
    return [BookHit(book_id=r.id, title=r.title, series_id=r.series_id, series_title=r.series_title,
                    library_id=r.library_id, library_name=r.library_name, file_format=r.file_format,
                    cover_path=r.cover_path) for r in rows]  # fmt: skip


def _snippet(marked: str) -> str:
    return html.escape(marked).replace(_START, "<mark>").replace(_STOP, "</mark>")


def fulltext(db: Session, query: str, *, book_id: int | None = None, library_id: int | None = None,
             limit: int = 30) -> list[TextHit]:  # fmt: skip
    if not _words(query):
        return []
    params: dict[str, Any] = {"q": query, "limit": limit,
                              "options": f"StartSel={_START},StopSel={_STOP},MaxWords=30,MinWords=12,MaxFragments=1"}  # fmt: skip
    scope = ""
    if book_id is not None:
        scope += " AND c.book_id = :book_id"
        params["book_id"] = book_id
    if library_id is not None:
        scope += " AND b.library_id = :library_id"
        params["library_id"] = library_id
    rows = db.execute(
        text(
            "WITH q AS (SELECT websearch_to_tsquery('simple', :q) AS tsq)"
            " SELECT c.book_id, b.library_id, coalesce(m.title, b.file_path) AS title, c.position,"
            "  ts_headline('simple', c.text, q.tsq, :options) AS snippet"
            " FROM content_index_entries c JOIN books b ON b.id = c.book_id"
            " LEFT JOIN book_metadata m ON m.book_id = b.id, q"
            " WHERE to_tsvector('simple', c.text) @@ q.tsq AND b.missing_since IS NULL" + scope +
            " ORDER BY ts_rank(to_tsvector('simple', c.text), q.tsq) DESC, c.id LIMIT :limit"
        ),
        params,
    ).all()  # fmt: skip
    return [TextHit(book_id=r.book_id, library_id=r.library_id, title=r.title, position=r.position,
                    snippet=_snippet(r.snippet)) for r in rows]  # fmt: skip
