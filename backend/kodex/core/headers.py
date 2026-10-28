"""Security headers on every response, not only the web client's pages
(kodex.core.spa adds its CSP): no content-type sniffing, no referrer to
other sites, and no framing by another site. A header a response sets
itself wins. HSTS is the TLS proxy's to set, since Kodex doesn't know
whether it is reached over HTTPS."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"referrer-policy": b"same-origin",
    b"x-frame-options": b"SAMEORIGIN",
}


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                message["headers"] = [*message.get("headers", []),
                                      *((k, v) for k, v in HEADERS.items() if k not in present)]  # fmt: skip
            await send(message)

        await self.app(scope, receive, with_headers)
