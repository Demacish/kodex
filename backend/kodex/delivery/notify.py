"""Notifications, all best-effort: to the admins on Telegram and Discord
(a new request, a new release in a followed series), and to each user on
their own ntfy topic (new books in a series they follow).

Sent right away from the code that caused them: one webhook call is quick.
None of them may turn into a failure of what caused it. The request or
book is already saved, so a Telegram outage costs only the message, and a
short timeout keeps a slow endpoint from being felt.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

import httpx

from app.models.enums import BookEditionType

if TYPE_CHECKING:
    from app.config import Settings
    from app.models.book import Book
    from app.models.request import Request
    from app.models.series import Series
    from app.models.user import User

logger = logging.getLogger(__name__)

_MEDIA_TYPE_LABELS = {"series": "Serie", "ebook": "E-bok", "manga": "Manga"}
_TIMEOUT = 5.0


def _format_message(request: Request) -> str:
    media_label = _MEDIA_TYPE_LABELS.get(request.media_type.value, request.media_type.value)
    lines = [f"📬 Nytt önskemål i Kodex: {request.title} ({media_label})"]
    if request.external_link:
        lines.append(request.external_link)
    return "\n".join(lines)


def _send_telegram(message: str, *, settings: Settings) -> None:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    httpx.post(url, json={"chat_id": settings.telegram_chat_id, "text": message}, timeout=_TIMEOUT).raise_for_status()


def _send_discord(message: str, *, settings: Settings) -> None:
    httpx.post(settings.discord_webhook_url, json={"content": message}, timeout=_TIMEOUT).raise_for_status()


def _to_admins(message: str, about: str, *, settings: Settings) -> bool:
    """Telegram and Discord, whichever are set up; True when one of them took it."""
    if not settings.telegram_bot_token and not settings.discord_webhook_url:
        logger.info("No Telegram or Discord set up: %s without a notification", about)
        return False
    sent = False
    if settings.telegram_bot_token and settings.telegram_chat_id:
        try:
            _send_telegram(message, settings=settings)
            sent = True
        except Exception:
            logger.exception("Telegram notification for %s failed", about)
    if settings.discord_webhook_url:
        try:
            _send_discord(message, settings=settings)
            sent = True
        except Exception:
            logger.exception("Discord notification for %s failed", about)
    return sent


def notify_new_request(request: Request, *, settings: Settings) -> bool:
    return _to_admins(_format_message(request), f"request {request.id}", settings=settings)


def notify_bulk_requests(count: int, collection_name: str, *, settings: Settings) -> bool:
    """One message for "Begär saknade nummer" on a story arc, not one per issue."""
    message = f'📬 {count} nya önskemål i Kodex: saknade nummer i "{collection_name}"'
    return _to_admins(message, f"{count} requests from {collection_name!r}", settings=settings)


def notify_new_release(series: Series, *, settings: Settings) -> bool:
    """A followed series has a new release. The caller sends it only when
    Series.new_release_available turns true; this has no memory of its own."""
    return _to_admins(f"🆕 Ny utgåva tillgänglig i Kodex: {series.title}", f"series {series.id}", settings=settings)


def send_ntfy(topic: str, *, title: str, message: str, click: str | None, settings: Settings) -> None:
    """One push through ntfy's JSON API (ntfy.sh or a server of your own,
    and UnifiedPush apps through it); JSON so Swedish titles need no
    encoding."""
    payload: dict[str, Any] = {"topic": topic, "title": title, "message": message, "tags": ["books"]}
    if click:
        payload["click"] = click
    headers = {"Authorization": f"Bearer {settings.ntfy_token}"} if settings.ntfy_token else {}
    httpx.post(settings.ntfy_url.rstrip("/"), json=payload, headers=headers, timeout=_TIMEOUT).raise_for_status()


def _volume_label(book: Book) -> str:
    if book.number is None:
        return book.book_metadata.title if book.book_metadata else book.file_path
    number: float | int = int(book.number) if float(book.number).is_integer() else book.number
    return f"Vol. {number}" if book.edition_type == BookEditionType.COLLECTED else f"#{number}"


def notify_new_books(series: Series, books: Sequence[Book], users: Iterable[User], *, settings: Settings) -> int:
    """One push per user with an ntfy topic ("Ny volym i Saga: #55", "3 nya
    volymer i Saga: #55, #56, #57"); how many were sent. One bad topic
    doesn't stop the rest."""
    ordered = sorted(
        books, key=lambda b: (b.edition_type == BookEditionType.COLLECTED, b.number is None, b.number or 0)
    )
    labels = [_volume_label(book) for book in ordered]
    title = f"Ny volym i {series.title}" if len(books) == 1 else f"{len(books)} nya volymer i {series.title}"
    message = ", ".join(labels[:10]) + (" …" if len(labels) > 10 else "")
    click = f"{settings.public_app_url.rstrip('/')}/series/{series.id}" if settings.public_app_url else None
    sent = 0
    for user in users:
        if not user.ntfy_topic:
            continue
        try:
            send_ntfy(user.ntfy_topic, title=title, message=message, click=click, settings=settings)
            sent += 1
        except Exception:
            logger.exception("ntfy push to %s failed", user.ntfy_topic)
    return sent
