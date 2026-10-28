from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import AISuggestionStatus, RequestMediaType

if TYPE_CHECKING:
    from app.models.request import Request
    from app.models.user import User


class AIRecommendation(Base):
    """One cached "you might like this" suggestion from app/ai/
    recommendations.py, scoped to a single user (personalization is based
    on that user's own ReadingProgress/genres, see build_user_context) —
    unlike the rest of this app's shared-catalog model, this table is
    genuinely per-user, same reasoning as ReadingProgress.

    A brand new table, not a column on an existing one — same "no Alembic
    yet, so a new table is the only zero-risk schema change" reasoning as
    BookPagePanel (see app/models/panel.py).
    """

    __tablename__ = "ai_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    title: Mapped[str] = mapped_column(String(500))
    author: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Free text from the LLM explaining the suggestion (e.g. "eftersom du
    # gillade X") — shown on the recommendation card, never parsed.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Best-effort guess at which Request.media_type this becomes if swiped
    # right — the LLM is asked for one of "series"/"ebook"/"manga" directly
    # (see app/ai/recommendations.py's prompt), so no separate classifier.
    media_type_guess: Mapped[RequestMediaType | None] = mapped_column(
        Enum(RequestMediaType, native_enum=False), nullable=True
    )
    # Best-effort thumbnail from a provider search at generation time (see
    # app/ai/covers.py) — a suggestion is never something the user owns,
    # so there's no local cover to fall back to; null just means the
    # lookup found nothing or was skipped (rate limit/no key configured).
    # THIS TABLE ALREADY EXISTS IN PRODUCTION (created by an earlier
    # create_all() run this same deployment round) — adding this column
    # NEEDS A MANUAL `ALTER TABLE ai_recommendations ADD COLUMN cover_url
    # VARCHAR(1024);` same as every other column added to an
    # already-existing table in this project (no Alembic yet).
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    status: Mapped[AISuggestionStatus] = mapped_column(
        Enum(AISuggestionStatus, native_enum=False), default=AISuggestionStatus.SUGGESTED
    )
    # Set only once swiped right and a Request actually got created from
    # this suggestion (see the /ai/recommendations/{id}/swipe route).
    # SET NULL rather than CASCADE: deleting the Request later (there's no
    # such endpoint today, but see collection_id's identical reasoning on
    # Request itself) shouldn't silently delete the recommendation history.
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship()
    request: Mapped[Request | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIRecommendation id={self.id} title={self.title!r} status={self.status}>"
