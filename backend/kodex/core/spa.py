"""Serves the web client (web/, a Vite build) from the api: its files as
they are, and index.html for any page the browser navigates to, so the
client's own router takes over. v1's API also answers at the root (until
the Android app moves to /api), and paths like /series/12 are both a page
and an endpoint, so what decides is whether the browser is loading a
document (Sec-Fetch-Dest, or Accept for browsers without it) rather than
the path."""

from __future__ import annotations

import logging
from pathlib import Path

from starlette.datastructures import Headers
from starlette.responses import FileResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Never the web client's: the API, the protocols and the health check.
_NOT_PAGES = ("/api/", "/opds", "/kosync", "/kobo/", "/federation", "/healthz", "/readyz")
_IMMUTABLE = "public, max-age=31536000, immutable"  # Vite's hashed files under assets/
_REVALIDATE = "no-cache"
# Books are untrusted: the EPUB reader renders them in same-origin frames
# (blob: documents, which inherit this policy), so no script runs that
# isn't one of the app's own files. pdf.js needs WebAssembly; covers from
# recommendations may come from other sites.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'wasm-unsafe-eval'",
        "style-src 'self' 'unsafe-inline' blob:",
        "img-src 'self' data: blob: https:",
        "font-src 'self' data: blob:",
        "media-src 'self' blob:",
        "connect-src 'self'",
        "frame-src 'self' blob:",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self'",
    ]
)
_PAGE_HEADERS = {
    "cache-control": _REVALIDATE,
    "content-security-policy": CONTENT_SECURITY_POLICY,
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
}


def is_navigation(headers: Headers) -> bool:
    dest = headers.get("sec-fetch-dest")
    if dest is not None:
        return dest in ("document", "iframe")
    return "text/html" in headers.get("accept", "")


class WebClient:
    def __init__(self, app: ASGIApp, dist: str | Path) -> None:
        self.app = app
        root = Path(dist)
        self.index = root / "index.html"
        self.files: dict[str, Path] = {}
        if self.index.is_file():
            self.files = {
                "/" + p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file() and p != self.index
            }
        else:
            logger.info("No web client at %s; serving the API only", root)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in ("GET", "HEAD") and self.files:
            path: str = scope["path"]
            if not path.startswith(_NOT_PAGES):
                if path == "/index.html":  # the service worker precaches the page by name
                    await FileResponse(self.index, media_type="text/html", headers=_PAGE_HEADERS)(scope, receive, send)
                    return
                file = self.files.get(path)
                if file is not None:
                    cache = _IMMUTABLE if path.startswith("/assets/") else _REVALIDATE
                    await FileResponse(file, headers={"cache-control": cache})(scope, receive, send)
                    return
                if is_navigation(Headers(scope=scope)):
                    await FileResponse(self.index, media_type="text/html", headers=_PAGE_HEADERS)(scope, receive, send)
                    return
        await self.app(scope, receive, send)
