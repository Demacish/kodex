"""The change log apps sync from (kodex.core.sync), written by database
triggers (migration 0014)."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from kodex.core.db import Base


class SyncLog(Base):
    """One change: a library, series, book or collection (``entity``) that
    was written, or ``deleted``, in the order of ``seq``."""

    __tablename__ = "sync_log"
    __table_args__ = (Index("ix_sync_log_entity_entity_id", "entity", "entity_id"),)

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity: Mapped[str] = mapped_column(String(16))
    entity_id: Mapped[int] = mapped_column(Integer)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
