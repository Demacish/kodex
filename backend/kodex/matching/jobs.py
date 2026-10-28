"""Matching as background work: one series, or every series of a library
that still needs it. Run by the worker (app/workers/tasks.py); a used-up
provider budget ends the run early and the rest waits for the next one."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.library import Library
from app.models.series import Series
from kodex.matching.engine import Matcher, ProviderSet, build_providers, library_kind
from kodex.matching.providers.base import ProviderError, RateLimited

logger = logging.getLogger(__name__)

# Series in these states are (re)matched by a library run.
_PENDING = ("unmatched",)


def match_series_list(
    db: Session, matcher: Matcher, series_list: list[Series], *, force: bool = False
) -> dict[str, Any]:
    result: dict[str, Any] = {"auto": 0, "review": 0, "none": 0, "skipped": 0, "errors": 0, "rate_limited_until": None}
    for series in series_list:
        try:
            outcome = matcher.match_series(series, force=force)
            db.commit()
        except RateLimited as exc:
            db.rollback()
            result["rate_limited_until"] = exc.retry_at.isoformat()
            logger.warning("Matching paused: %s", exc)
            break
        except ProviderError as exc:
            db.rollback()
            result["errors"] += 1
            logger.warning("Matching series %s failed: %s", series.id, exc)
            continue
        key = "skipped" if outcome.via == "skipped" else outcome.decision.outcome
        result[key] += 1
    return result


def match_library(
    db: Session, library_id: int, *, providers: ProviderSet | None = None, force: bool = False
) -> dict[str, Any]:
    library = db.get(Library, library_id)
    if library is None:
        raise ValueError(f"Library {library_id} not found")
    statuses = ("unmatched", "review", "auto") if force else _PENDING
    series_list = list(
        db.scalars(
            select(Series).where(Series.library_id == library_id, Series.match_status.in_(statuses)).order_by(Series.id)
        )
    )
    providers = providers or build_providers(db.get_bind(), library_kind(library))  # type: ignore[arg-type]
    try:
        return match_series_list(db, Matcher(db, providers), series_list, force=force)
    finally:
        providers.close()


def match_one(db: Session, series_id: int, *, providers: ProviderSet | None = None) -> dict[str, Any]:
    series = db.get(Series, series_id)
    if series is None:
        raise ValueError(f"Series {series_id} not found")
    library = db.get(Library, series.library_id)
    assert library is not None
    providers = providers or build_providers(db.get_bind(), library_kind(library))  # type: ignore[arg-type]
    try:
        return match_series_list(db, Matcher(db, providers), [series], force=True)
    finally:
        providers.close()
