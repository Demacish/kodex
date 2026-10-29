"""The reading journal: every position a device reported, in the order the
server received them. ``reading_progress`` holds the current state, derived
from the journal (kodex.reading.journal), which compacts old entries."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from kodex.core.db import Base


class ReadingEvent(Base):
    __tablename__ = "reading_events"
    __table_args__ = (Index("ix_reading_events_user_id_book_id_received_at", "user_id", "book_id", "received_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    # A random id each client keeps (a browser: in local storage), with a
    # name for people, and the client's own counter, which orders a device's
    # reports when the network delivers them late or twice.
    device_id: Mapped[str] = mapped_column(String(64))
    device_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    client_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16))  # progress | finished | reset
    # The reader's own locator and its kind (kodex.reading.positions).
    position: Mapped[str | None] = mapped_column(String(512), nullable=True)
    locator_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    progress_percent: Mapped[float] = mapped_column(Float)
    chapter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KoboDevice(Base):
    """A Kobo e-reader syncing through one of its user's Kobo keys
    (kodex.reading.kobo): the books of ``collection_id`` that are EPUBs."""

    __tablename__ = "kobo_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id", ondelete="CASCADE"), unique=True)
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id", ondelete="SET NULL"), nullable=True)
    last_sync_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KoboBook(Base):
    """A book the device was given, and when; ``removed`` once it was told
    to drop it."""

    __tablename__ = "kobo_books"

    device_id: Mapped[int] = mapped_column(ForeignKey("kobo_devices.id", ondelete="CASCADE"), primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), primary_key=True)
    synced_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    removed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class Bookmark(Base):
    """A place in a book the user wants to find again, on any device. The id
    is the client's own (a UUID): a device makes one offline and sends it
    when it can, as often as it has to (kodex.reading.bookmarks)."""

    __tablename__ = "bookmarks"
    __table_args__ = (Index("ix_bookmarks_user_id_book_id", "user_id", "book_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    # A locator in the kind of the reader that made it (kodex.reading.positions).
    position: Mapped[str] = mapped_column(String(512))
    locator_kind: Mapped[str] = mapped_column(String(16))
    progress_percent: Mapped[float] = mapped_column(Float)
    chapter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
