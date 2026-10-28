"""Tables owned by the matching engine.

- ``SeriesExternalId``: a series' ids at the providers; one series can be
  Comic Vine + Metron, or MangaDex + AniList + MAL + MangaUpdates at once.
- ``SeriesAlias``: a learned link from a normalised title (and year) to a
  provider id, positive ("this is that") or negative ("this is not that").
- ``ProviderCache`` and ``ProviderRateState``: every provider response is
  cached in the database, and rate-limit state lives here too so several
  workers share one budget.
- ``MatchReview``: the review queue, and the log of automatic decisions
  (status ``auto``) so every one of them can be reverted.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from kodex.core.db import Base

Polarity = Literal["positive", "negative"]
ReviewKind = Literal["series_match", "book_match", "issue_match", "regroup", "split", "duplicate"]
ReviewStatus = Literal["open", "auto", "resolved", "dismissed", "reverted"]


class SeriesExternalId(Base):
    __tablename__ = "series_external_ids"
    __table_args__ = (
        UniqueConstraint("series_id", "provider", "external_id"),
        Index("ix_series_external_ids_provider_external_id", "provider", "external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # embedded | auto | manual | alias | bridge (learned from another provider's links)
    source: Mapped[str] = mapped_column(String(16), default="auto", server_default="auto")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SeriesAlias(Base):
    __tablename__ = "series_aliases"
    __table_args__ = (
        UniqueConstraint(
            "norm_title",
            "year",
            "library_id",
            "provider",
            "external_id",
            "polarity",
            name="uq_series_aliases_target",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    norm_title: Mapped[str] = mapped_column(String(500), index=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    library_id: Mapped[int | None] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), nullable=True)
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))
    polarity: Mapped[str] = mapped_column(String(8), default="positive", server_default="positive")
    # manual (a review decision) | provider (the provider's own synonyms)
    source: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProviderCache(Base):
    __tablename__ = "provider_cache"
    __table_args__ = (UniqueConstraint("provider", "query_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    query_hash: Mapped[str] = mapped_column(String(64))
    # The request without credentials, for debugging and cache inspection.
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[int] = mapped_column(Integer)
    payload: Mapped[Any] = mapped_column(JSON)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)


class ProviderRateState(Base):
    __tablename__ = "provider_rate_state"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    # A provider can limit per resource (Comic Vine counts per endpoint).
    bucket: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reset_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_allowed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MatchReview(Base):
    __tablename__ = "match_reviews"
    __table_args__ = (
        Index("ix_match_reviews_status_library", "status", "library_id"),
        # At most one open item per kind and target.
        Index(
            "uq_match_reviews_open_target",
            "kind",
            "series_id",
            "book_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"))
    # SET NULL: the history of decisions outlives the series and books.
    series_id: Mapped[int | None] = mapped_column(ForeignKey("series.id", ondelete="SET NULL"), nullable=True)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    book_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # What the engine saw: parsed tokens, evidence, and up to a few scored
    # candidates with their per-signal scores.
    parsed: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    best_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # What was decided, and what it replaced (for reverting an auto decision).
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    previous: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suggestion: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
