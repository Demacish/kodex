"""Fetching addresses that came from someone else's data (a provider's
cover URL, say): only http and https, and never to this machine or its
network. Without the guard, a provider's data could make the server fetch
from the server's own network for whoever wrote the data (SSRF).

The services an admin sets up (Prowlarr, qBittorrent, ntfy, …) are meant
to be on the local network and are fetched without it. Their addresses
come only from the environment, never from the web client.

The check runs for every request a client makes, so a redirect to a
private address is refused too. The address is resolved once to check it;
a name that resolves differently a moment later (DNS rebinding) isn't
caught.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

import httpx


class Refused(httpx.RequestError):
    """Not an address this server fetches for someone else's data."""


def _blocked(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (address.is_private or address.is_loopback or address.is_link_local or address.is_multicast
            or address.is_reserved or address.is_unspecified)  # fmt: skip


def _private(host: str) -> bool:
    try:
        return _blocked(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        pass  # a name, not an address
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:  # noqa: BLE001 - unresolvable: the request itself will fail and say why
        return False
    return any(_blocked(ipaddress.ip_address(info[4][0])) for info in infos)


def check(request: httpx.Request) -> None:
    if request.url.scheme not in ("http", "https"):
        raise Refused(f"Not fetched: {request.url.scheme} addresses", request=request)
    host = request.url.host
    if not host or _private(host):
        raise Refused(f"Not fetched: {host} is on this machine or its network", request=request)


def client(**kwargs: Any) -> httpx.Client:
    """An httpx client for third-party addresses (``kwargs`` as for httpx.Client)."""
    hooks = dict(kwargs.pop("event_hooks", {}) or {})
    hooks["request"] = [check, *hooks.get("request", [])]
    return httpx.Client(event_hooks=hooks, **kwargs)
