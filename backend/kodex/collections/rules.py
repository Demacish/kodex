"""Smart collections' rules, compiled to SQL (in place of Meilisearch
filters): a rule tree becomes a condition on books outer-joined to their
metadata (kodex.collections.members), evaluated for the user looking at
the collection.

    {"all": [<rule>, ...]}    every rule holds
    {"any": [<rule>, ...]}    one of them holds
    {"not": <rule>}           it doesn't hold
    {"field": "genres", "op": "eq", "value": "Fantasy"}

Fields and operators:

- ``genres``, ``tags``, ``authors``, ``story_arcs``: eq/contains (the book
  has it), neq;
- ``title``, ``publisher``, ``series``: eq, neq, contains (case-insensitive);
- ``library_id``, ``series_id``: eq, neq; ``file_format``: eq, neq;
- ``year``: eq, neq, gte, lte (the publication year);
- ``read_status``: eq/neq ``unread``, ``reading`` or ``finished``, for the
  user;
- ``following``: eq true/false, the book's series is followed;
- ``next_unread``: eq true, the first book of its series, in reading
  order, that the user hasn't finished ("olästa i serie": with
  ``following`` it is the next book of every followed series).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, and_, cast, exists, false, func, not_, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import aliased

from app.models.book import Book
from app.models.enums import BookFormat
from app.models.metadata import BookMetadata
from app.models.reading_progress import ReadingProgress
from app.models.series import Series

ARRAYS = ("genres", "tags", "authors", "story_arcs")
TEXTS = {"title": BookMetadata.title, "publisher": BookMetadata.publisher}
OPS = {"eq", "contains", "neq", "gte", "lte"}


class RuleError(ValueError):
    """A rule is malformed or uses a field or operator there isn't; shown
    to the caller as a 400, never an empty collection."""


def _metadata(condition: ColumnElement[bool]) -> ColumnElement[bool]:
    """A condition on the book's metadata, which the query outer-joins: a
    book without metadata doesn't match it."""
    return func.coalesce(condition, false())


def _progress(user_id: int, condition: ColumnElement[bool]) -> ColumnElement[bool]:
    return exists(select(ReadingProgress.id).where(ReadingProgress.book_id == Book.id,
                                                   ReadingProgress.user_id == user_id, condition))  # fmt: skip


def _finished(user_id: int, book: Any) -> ColumnElement[bool]:
    return exists(select(ReadingProgress.id).where(ReadingProgress.book_id == book.id, ReadingProgress.user_id == user_id,
                                                   ReadingProgress.is_finished.is_(True)))  # fmt: skip


def _next_unread(user_id: int) -> ColumnElement[bool]:
    """Not finished, and no unfinished book comes before it in its series."""
    earlier = aliased(Book)
    before = or_(func.coalesce(earlier.number, 1e9) < func.coalesce(Book.number, 1e9),
                 and_(func.coalesce(earlier.number, 1e9) == func.coalesce(Book.number, 1e9),
                      earlier.file_path < Book.file_path))  # fmt: skip
    blocking = exists(select(earlier.id).where(earlier.series_id == Book.series_id, earlier.missing_since.is_(None),
                                               before, not_(_finished(user_id, earlier))))  # fmt: skip
    return and_(Book.series_id.isnot(None), not_(_finished(user_id, Book)), not_(blocking))


def _leaf(rule: dict[str, Any], user_id: int) -> ColumnElement[bool]:
    field, op = rule.get("field"), rule.get("op", "eq")
    if "value" not in rule:
        raise RuleError(f"The rule for {field!r} has no 'value'")
    value = rule["value"]
    if op not in OPS:
        raise RuleError(f"Unknown operator {op!r}")
    condition: ColumnElement[bool]
    if field in ARRAYS:
        if op not in ("eq", "contains", "neq"):
            raise RuleError(f"{field} takes eq, contains or neq")
        column = getattr(BookMetadata, str(field))
        condition = _metadata(cast(column, JSONB).contains([str(value)]))
        return not_(condition) if op == "neq" else condition
    if field in TEXTS or field == "series":
        if op not in ("eq", "contains", "neq"):
            raise RuleError(f"{field} takes eq, contains or neq")
        text = str(value).lower()
        if field == "series":
            target = func.lower(Series.title)
            matched = target.contains(text, autoescape=True) if op == "contains" else target == text
            condition = exists(select(Series.id).where(Series.id == Book.series_id, matched))
        else:
            target = func.lower(TEXTS[str(field)])
            matched = target.contains(text, autoescape=True) if op == "contains" else target == text
            condition = _metadata(matched)
        return not_(condition) if op == "neq" else condition
    if field in ("library_id", "series_id"):
        if op not in ("eq", "neq") or not isinstance(value, int) or isinstance(value, bool):
            raise RuleError(f"{field} takes eq or neq and a number")
        column = Book.library_id if field == "library_id" else Book.series_id
        return column != value if op == "neq" else column == value
    if field == "file_format":
        try:
            fmt = BookFormat(str(value).lower())
        except ValueError as exc:
            raise RuleError(f"Unknown file format {value!r}") from exc
        if op not in ("eq", "neq"):
            raise RuleError("file_format takes eq or neq")
        return Book.file_format != fmt if op == "neq" else Book.file_format == fmt
    if field == "year":
        if not isinstance(value, int) or isinstance(value, bool):
            raise RuleError("year takes a number")
        year = BookMetadata.published_year
        compare = {"eq": year == value, "neq": year != value, "gte": year >= value, "lte": year <= value}
        if op not in compare:
            raise RuleError("year takes eq, neq, gte or lte")
        return _metadata(compare[op])
    if field == "read_status":
        states = {"unread": not_(_progress(user_id, or_(ReadingProgress.progress_percent > 0,
                                                        ReadingProgress.is_finished.is_(True)))),
                  "reading": _progress(user_id, and_(ReadingProgress.progress_percent > 0,
                                                     ReadingProgress.is_finished.is_(False))),
                  "finished": _progress(user_id, ReadingProgress.is_finished.is_(True))}  # fmt: skip
        if value not in states or op not in ("eq", "neq"):
            raise RuleError("read_status takes eq or neq and unread, reading or finished")
        return not_(states[value]) if op == "neq" else states[value]
    if field == "following":
        if not isinstance(value, bool) or op != "eq":
            raise RuleError("following takes eq and true or false")
        followed = exists(select(Series.id).where(Series.id == Book.series_id, Series.is_following.is_(True)))
        return followed if value else not_(followed)
    if field == "next_unread":
        if value is not True or op != "eq":
            raise RuleError("next_unread takes eq and true")
        return _next_unread(user_id)
    raise RuleError(f"Unknown field {field!r}")


def compile_rule(rule: Any, user_id: int) -> ColumnElement[bool]:
    """The condition on books a rule stands for. Raises RuleError."""
    if not isinstance(rule, dict):
        raise RuleError("A rule must be an object")
    for key, combine in (("all", and_), ("any", or_)):
        if key in rule:
            parts = rule[key]
            if not isinstance(parts, list) or not parts:
                raise RuleError(f"'{key}' must be a non-empty list of rules")
            return combine(*(compile_rule(part, user_id) for part in parts))
    if "not" in rule:
        return not_(compile_rule(rule["not"], user_id))
    if "field" in rule:
        return _leaf(rule, user_id)
    raise RuleError("A rule must contain 'all', 'any', 'not' or 'field'")


def validate(rule: Any) -> None:
    compile_rule(rule, 0)


def single_story_arc(rule: Any) -> str | None:
    """The arc of a rule that is exactly one story arc, whose books read in
    the arc's order."""
    if isinstance(rule, dict) and rule.get("field") == "story_arcs" and "value" in rule:
        return str(rule["value"])
    return None
