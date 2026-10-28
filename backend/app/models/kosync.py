from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KosyncProgress(Base):
    """The last accepted KOReader-sync position per user and document (a
    book's content_hash, see app/scanning/fingerprint.py) — kept even when
    no book on THIS server has that hash, since this server is also the
    central sync point for other Kodex servers and KOReader devices whose
    files it may not hold itself. When a local book does match, its
    ReadingProgress is updated too (see app/progress/sync.py).

    `progress` is whatever the client sent: a page number for page-based
    documents, an XPointer for KOReader's EPUB engine. A brand new table —
    create_all() creates it, no manual migration needed.
    """

    __tablename__ = "kosync_progress"
    __table_args__ = (UniqueConstraint("user_id", "document", name="uq_kosync_user_document"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    document: Mapped[str] = mapped_column(String(64))
    progress: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    percentage: Mapped[float] = mapped_column(Float, default=0.0)
    device: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
