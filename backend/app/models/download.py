from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import DownloadClientType, DownloadSource, DownloadStatus

if TYPE_CHECKING:
    from app.models.library import Library
    from app.models.request import Request
    from app.models.user import User


class Download(Base):
    """One tracked download — a torrent/nzb handed to qBittorrent/SABnzbd,
    or a direct file fetch (Anna's Archive/GetComics). See kodex/acquire/clients/
    for the client abstraction and app/workers/tasks.py's
    start_download_task/import_completed_download_task for the job
    lifecycle this row's `status` moves through.

    A brand new table — inget manuellt ALTER TABLE behövs.
    """

    __tablename__ = "downloads"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Set only when this download was triggered from an approved Request
    # (see requests.py's Batch-C tie-in) — null for one an admin started
    # directly from a search result with no linked request.
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id", ondelete="SET NULL"), nullable=True)

    source: Mapped[DownloadSource] = mapped_column(Enum(DownloadSource, native_enum=False))
    client: Mapped[DownloadClientType] = mapped_column(Enum(DownloadClientType, native_enum=False))
    # The download client's own id for this item (torrent hash / SABnzbd
    # nzo_id) — null for a DIRECT_HTTP download, which has no such
    # external tracking id (the worker just streams the file itself).
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(500))

    status: Mapped[DownloadStatus] = mapped_column(
        Enum(DownloadStatus, native_enum=False), default=DownloadStatus.QUEUED
    )
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Where the finished file lands before import_completed_download_task
    # moves it into library_id's folder — under settings.
    # downloads_staging_dir, path-mapped per DOWNLOAD_PATH_MAP_TORRENT/
    # USENET if the download client runs in a different container/host
    # than Kodex's own worker (see that setting's own docstring).
    save_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    library_id: Mapped[int | None] = mapped_column(ForeignKey("libraries.id", ondelete="SET NULL"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # foreign_keys pinned explicitly — Request also has its own download_id
    # FK back to this table (Batch-C auto-download tie-in), so without
    # this SQLAlchemy can't auto-pick which of the two requests<->downloads
    # foreign keys this relationship means.
    request: Mapped[Request | None] = relationship(foreign_keys=[request_id])
    library: Mapped[Library | None] = relationship()
    created_by: Mapped[User | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Download id={self.id} title={self.title!r} status={self.status}>"
