"""Kobo's store, for what the sync doesn't answer itself: the device's
account, store purchases, deals and settings go on to storeapi.kobo.com as
the device sent them (only that host). Off with ``KOBO_STORE_PROXY=false``;
then those requests get empty answers."""

from __future__ import annotations

import logging
import secrets
import uuid
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.config import get_settings

logger = logging.getLogger(__name__)

STORE = "https://storeapi.kobo.com"
IMAGES = "https://cdn.kobo.com/book-images"
_TIMEOUT = 10.0
_DROP = {"host", "content-length", "accept-encoding", "connection", "x-forwarded-for", "x-forwarded-proto",
         "x-forwarded-host", "cookie"}  # fmt: skip
_PASS_BACK = ("content-type", "x-kobo-synctoken", "x-kobo-sync", "x-kobo-apitoken", "x-kobo-recent-reads")


def enabled() -> bool:
    return get_settings().kobo_store_proxy


def client() -> httpx.Client:
    """Replaced in tests with one on an httpx.MockTransport."""
    return httpx.Client(timeout=_TIMEOUT, follow_redirects=False)


def forward(request: Request, path: str, body: bytes, headers: dict[str, str] | None = None) -> httpx.Response | None:
    """The store's answer to the device's request, or None when it can't be
    asked (turned off, or unreachable). ``headers`` replace the device's;
    an empty value leaves one out."""
    if not enabled():
        return None
    sent = {k: v for k, v in request.headers.items() if k.lower() not in _DROP}
    for name, value in (headers or {}).items():
        if value:
            sent[name] = value
        else:
            sent.pop(name, None)
    try:
        with client() as store:
            return store.request(request.method, f"{STORE}/{path.lstrip('/')}", params=request.query_params,
                                 content=body or None, headers=sent)  # fmt: skip
    except httpx.HTTPError as exc:
        logger.info("Kobo's store didn't answer %s: %s", path, exc)
        return None


def relay(answer: httpx.Response) -> Response:
    headers = {k: v for k, v in answer.headers.items() if k.lower() in _PASS_BACK}
    return Response(answer.content, status_code=answer.status_code, headers=headers)


def empty(path: str) -> Response:
    """What a request the store would answer gets without it."""
    if path.endswith("/v1/auth/device") or path.endswith("/v1/auth/refresh"):
        return JSONResponse({"AccessToken": secrets.token_urlsafe(24), "RefreshToken": secrets.token_urlsafe(24),
                             "TokenType": "Bearer", "TrackingId": str(uuid.uuid4()), "UserKey": ""})  # fmt: skip
    return JSONResponse({})


def resources(answer: httpx.Response | None) -> dict[str, Any]:
    """The store's resources, or the ones the device needs without it."""
    if answer is not None and answer.status_code == 200:
        try:
            found = answer.json().get("Resources")
        except ValueError:
            found = None
        if isinstance(found, dict):
            return found
    return dict(_RESOURCES)


# The library and image entries a device needs when the store can't be
# asked, after Calibre-Web's and Komga's lists; the device sends the
# storeapi.kobo.com ones to its api_endpoint, which is this server.
_RESOURCES: dict[str, Any] = {
    "library_sync": f"{STORE}/v1/library/sync",
    "library_items": f"{STORE}/v1/user/library",
    "library_metadata": f"{STORE}/v1/library/{{Ids}}/metadata",
    "library_book": f"{STORE}/v1/user/library/books/{{LibraryItemId}}",
    "reading_state": f"{STORE}/v1/library/{{Ids}}/state",
    "delete_entitlement": f"{STORE}/v1/library/{{Ids}}",
    "add_entitlement": f"{STORE}/v1/library/{{RevisionIds}}",
    "tags": f"{STORE}/v1/library/tags",
    "tag_items": f"{STORE}/v1/library/tags/{{TagId}}/Items",
    "delete_tag": f"{STORE}/v1/library/tags/{{TagId}}",
    "delete_tag_items": f"{STORE}/v1/library/tags/{{TagId}}/items/delete",
    "rename_tag": f"{STORE}/v1/library/tags/{{TagId}}",
    "device_auth": f"{STORE}/v1/auth/device",
    "device_refresh": f"{STORE}/v1/auth/refresh",
    "user_profile": f"{STORE}/v1/user/profile",
    "configuration_data": f"{STORE}/v1/configuration",
    "get_tests_request": f"{STORE}/v1/analytics/gettests",
    "post_analytics_event": f"{STORE}/v1/analytics/event",
    "image_host": "https://cdn.kobo.com/book-images/",
    "image_url_template": f"{IMAGES}/{{ImageId}}/{{Width}}/{{Height}}/false/image.jpg",
    "image_url_quality_template": f"{IMAGES}/{{ImageId}}/{{Width}}/{{Height}}/{{Quality}}/{{IsGreyscale}}/image.jpg",
    "kobo_audiobooks_enabled": "False",
    "kobo_onestorelibrary_enabled": "False",
    "kobo_shelfie_enabled": "False",
    "kobo_subscriptions_enabled": "False",
    "kobo_superpoints_enabled": "False",
    "kobo_wishlist_enabled": "False",
    "kobo_nativeborrow_enabled": "False",
    "kobo_redeem_enabled": "False",
    "use_one_store": "False",
}
