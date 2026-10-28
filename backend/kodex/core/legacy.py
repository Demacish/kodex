"""v1's clients reached the API through the Next.js web app's proxy, at
``/api/backend/<path>`` (the Android app with an Authentik bearer token,
and OPDS and KOSync addresses copied from v1's settings). Those requests
are answered by the same routes as ``/<path>``, which v1's clients use
until the Android app moves to /api (phase 5)."""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

PREFIX = "/api/backend"


class V1Proxy:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path: str = scope["path"]
            if path == PREFIX or path.startswith(PREFIX + "/"):
                scope = dict(scope)
                scope["path"] = path[len(PREFIX) :] or "/"
                raw = scope.get("raw_path")
                if isinstance(raw, bytes) and raw.startswith(PREFIX.encode()):
                    scope["raw_path"] = raw[len(PREFIX) :] or b"/"
        await self.app(scope, receive, send)
