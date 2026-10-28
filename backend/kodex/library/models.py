"""Tables owned by the library module.

- ``BookFileHash``: every KOReader document id a book's file has had. The
  id is a hash of the file, so it changes when ComicInfo is written back or
  a CBR is converted, while a reading device keeps sending the old one;
  each id stays mapped to its book (see kodex.formats.identity).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from kodex.core.db import Base


class BookFileHash(Base):
    __tablename__ = "book_file_hashes"
    __table_args__ = (UniqueConstraint("kind", "value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="koreader", server_default="koreader")
    value: Mapped[str] = mapped_column(String(64))
    first_seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
