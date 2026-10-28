from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import RequestMediaType, RequestStatus

if TYPE_CHECKING:
    from app.models.collection import Collection
    from app.models.download import Download
    from app.models.user import User


class Request(Base):
    """A user-submitted "please add this" request — see the requestsystem
    section of the architecture plan. Notifications (Telegram/Discord) are
    sent from the API layer when a Request is created, not from this model.
    """

    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    title: Mapped[str] = mapped_column(String(500))
    media_type: Mapped[RequestMediaType] = mapped_column(Enum(RequestMediaType, native_enum=False))
    external_link: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[RequestStatus] = mapped_column(Enum(RequestStatus, native_enum=False), default=RequestStatus.PENDING)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set only for requests created via the "Begär saknade nummer" bulk
    # action on a story-arc collection (see collections.py's
    # request_missing_issues) — null for an ordinary one-off request.
    # SET NULL on delete rather than CASCADE: a collection being deleted
    # shouldn't wipe out the request history that came from it, only the
    # grouping. Lets the admin queue show/export "which collection did
    # this come from" (2026-09-11, requested).
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id", ondelete="SET NULL"), nullable=True)
    # Batch-C tie-in (C10-C11): opt-in only, set by POST /requests/{id}/
    # auto-download — never true by default, an admin has to explicitly
    # choose to try an automatic download for this request. Kept even
    # after a fallback to manual search so the admin queue can show
    # "auto-download was attempted" as a fact, independent of whether it
    # actually found a safe match.
    auto_download_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Set only when auto-download found a single safe match and queued
    # it — null while pending/fallen-back-to-manual. SET NULL (not
    # CASCADE): deleting the Download shouldn't delete the Request that
    # asked for it, same reasoning as collection_id above.
    # use_alter: downloads.request_id points back at this table, so this
    # one is created after both tables exist (see migration 0001).
    download_id: Mapped[int | None] = mapped_column(
        ForeignKey("downloads.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    # A missing issue of a series in the library (kodex.acquire): where the
    # file goes once downloaded, and the number that fulfils the request.
    series_id: Mapped[int | None] = mapped_column(
        ForeignKey("series.id", ondelete="SET NULL"), nullable=True, index=True
    )
    issue_number: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    requested_by: Mapped[User] = relationship()
    collection: Mapped[Collection | None] = relationship()
    download: Mapped[Download | None] = relationship(foreign_keys=[download_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Request id={self.id} title={self.title!r} status={self.status}>"
