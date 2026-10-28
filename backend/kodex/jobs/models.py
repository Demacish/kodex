"""What a job returned, or the error it failed with. Procrastinate keeps a
job's state but not its result, which the admin job view shows (a scan's
counts, an enrichment's matches)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from kodex.core.db import Base


class JobResult(Base):
    __tablename__ = "job_results"

    job_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    result: Mapped[Any] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
