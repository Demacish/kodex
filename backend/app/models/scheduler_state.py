from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SchedulerState(Base):
    """Tracks when a periodic, non-user-triggered job last actually ran —
    currently just the weekly followed-series release check (see
    v1 scheduler, now unused: kodex.jobs.periodic replaced it). One row per named task.

    A brand new table rather than a column added to an existing one, so
    this app's current `Base.metadata.create_all()`-only schema handling
    (see app/main.py's lifespan) is enough to bring it into existence —
    unlike the new columns added to Series in this same round, which need
    a real migration (or a dropped/recreated dev database) once a
    database already exists somewhere. See the architecture plan's
    "Modul: Följda serier" for that caveat.
    """

    __tablename__ = "scheduler_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_name: Mapped[str] = mapped_column(String(100), unique=True)
    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SchedulerState task_name={self.task_name!r} last_run_at={self.last_run_at}>"
