"""A user's tracker accounts and the series they link to entries there."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from kodex.core.db import Base


class TrackerAccount(Base):
    """A connected account. The tokens are encrypted (kodex.reading.trackers.secrets)."""

    __tablename__ = "tracker_accounts"
    __table_args__ = (UniqueConstraint("user_id", "service"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    service: Mapped[str] = mapped_column(String(16))
    # The account at the service: its id (for calls that need it) and the name people see.
    remote_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    username: Mapped[str] = mapped_column(String(255))
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrackerLink(Base):
    """A series followed at a service: what was sent last, and the last error."""

    __tablename__ = "tracker_links"
    __table_args__ = (UniqueConstraint("user_id", "series_id", "service"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True)
    service: Mapped[str] = mapped_column(String(16))
    remote_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500))
    # What a book in the series counts as there: "volume" or "chapter".
    unit: Mapped[str] = mapped_column(String(8))
    sent_progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
