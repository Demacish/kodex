"""Reading statistics from the journal: books finished per month, the days
something was read (for a calendar), the current and longest streak, and
pages read in paged formats. Days are UTC days. Past the journal's
retention a day keeps one entry per book, which is enough for all of it."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Day:
    date: dt.date
    books: int
    pages: int


@dataclass(frozen=True)
class Stats:
    finished_total: int
    in_progress: int
    finished_by_month: list[tuple[str, int]]  # ("2026-10", 3), oldest first, twelve months
    days: list[Day]
    current_streak: int
    longest_streak: int
    pages: int
    finished_by_type: dict[str, int]


def _months(today: dt.date, count: int) -> list[str]:
    months = []
    year, month = today.year, today.month
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return months[::-1]


def _streaks(dates: set[dt.date], today: dt.date) -> tuple[int, int]:
    longest = run = 0
    previous: dt.date | None = None
    for date in sorted(dates):
        run = run + 1 if previous is not None and date - previous == dt.timedelta(days=1) else 1
        longest = max(longest, run)
        previous = date
    current = 0
    day = today if today in dates else today - dt.timedelta(days=1)
    while day in dates:
        current += 1
        day -= dt.timedelta(days=1)
    return current, longest


def for_user(db: Session, user_id: int, today: dt.date, days: int = 365) -> Stats:
    since = today - dt.timedelta(days=days - 1)
    params = {"user": user_id, "since": since}
    totals = db.execute(
        text(
            "SELECT count(*) FILTER (WHERE is_finished),"
            " count(*) FILTER (WHERE NOT is_finished AND progress_percent > 0)"
            " FROM reading_progress WHERE user_id = :user"
        ),
        params,
    ).one()
    by_month: dict[str, int] = dict(
        db.execute(
            text(
                "SELECT to_char(received_at AT TIME ZONE 'UTC', 'YYYY-MM'), count(DISTINCT book_id)"
                " FROM reading_events WHERE user_id = :user AND kind = 'finished' GROUP BY 1"
            ),
            params,
        ).all()
    )
    # Pages: the forward steps between a book's successive page positions.
    rows = db.execute(
        text(
            "WITH steps AS ("
            " SELECT (received_at AT TIME ZONE 'UTC')::date AS day, book_id,"
            "  CASE WHEN locator_kind IN ('page', 'pdf') AND position ~ '^[0-9]+$' THEN position::int END AS page,"
            "  lag(CASE WHEN locator_kind IN ('page', 'pdf') AND position ~ '^[0-9]+$' THEN position::int END)"
            "   OVER (PARTITION BY book_id ORDER BY received_at, id) AS before"
            " FROM reading_events WHERE user_id = :user)"
            " SELECT day, count(DISTINCT book_id), coalesce(sum(greatest(page - before, 0)), 0)"
            " FROM steps WHERE day >= :since GROUP BY day ORDER BY day"
        ),
        params,
    ).all()
    by_type: dict[str, int] = dict(
        db.execute(
            text(
                "SELECT l.library_type, count(*) FROM reading_progress p JOIN books b ON b.id = p.book_id"
                " JOIN libraries l ON l.id = b.library_id WHERE p.user_id = :user AND p.is_finished GROUP BY 1"
            ),
            params,
        ).all()
    )
    calendar = [Day(date=row[0], books=int(row[1]), pages=int(row[2])) for row in rows]
    current, longest = _streaks({d.date for d in calendar}, today)
    return Stats(
        finished_total=int(totals[0]),
        in_progress=int(totals[1]),
        finished_by_month=[(m, int(by_month.get(m, 0))) for m in _months(today, 12)],
        days=calendar,
        current_streak=current,
        longest_streak=longest,
        pages=sum(d.pages for d in calendar),
        finished_by_type={str(k).lower(): int(v) for k, v in by_type.items()},
    )
