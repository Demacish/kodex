"""Which books are in a collection, in order: a manual collection's own
list (its set order, then the books added after), or what a smart
collection's rule matches for the user looking at it (by title, or a single
story arc in the arc's order)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.collection import Collection, collection_books
from app.models.enums import CollectionType
from app.models.metadata import BookMetadata
from kodex.collections import rules

LIMIT = 1000


def book_ids(db: Session, collection: Collection, user_id: int | None = None) -> list[int]:
    if collection.collection_type == CollectionType.MANUAL:
        query = (
            select(collection_books.c.book_id)
            .join(Book, Book.id == collection_books.c.book_id)
            .where(collection_books.c.collection_id == collection.id, Book.missing_since.is_(None))
            .order_by(collection_books.c.position.nulls_last(), Book.number.nulls_last(), Book.file_path)
        )
        return list(db.scalars(query))
    viewer = user_id if user_id is not None else collection.owner_user_id or 0
    condition = rules.compile_rule(collection.rule or {}, viewer)
    query = (select(Book.id, BookMetadata.story_arc_numbers).outerjoin(BookMetadata, BookMetadata.book_id == Book.id)
             .where(Book.missing_since.is_(None), condition)
             .order_by(BookMetadata.sort_title.nulls_last(), Book.number.nulls_last(), Book.id).limit(LIMIT))  # fmt: skip
    rows = db.execute(query).all()
    arc = rules.single_story_arc(collection.rule)
    if arc is None:
        return [row[0] for row in rows]

    def in_arc(row: tuple[int, dict[str, object] | None]) -> tuple[int, float]:
        number = (row[1] or {}).get(arc)
        try:
            return (0, float(number)) if number is not None else (1, 0.0)  # type: ignore[arg-type]
        except TypeError, ValueError:
            return (1, 0.0)

    # A collection of one story arc reads in the arc's order; issues without
    # a number in it come after, by title (the sort is stable).
    return [row[0] for row in sorted((tuple(r) for r in rows), key=in_arc)]
