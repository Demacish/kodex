"""Third-party addresses (kodex.core.outbound): http and https only, and
never this machine or its network, redirects included."""

from __future__ import annotations

import httpx
import pytest

from kodex.core import outbound


def _client(handler):
    return outbound.client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_public_addresses_are_fetched(monkeypatch):
    monkeypatch.setattr(outbound, "_private", lambda host: False)
    with _client(lambda request: httpx.Response(200, content=b"bild")) as client:
        assert client.get("https://covers.example/1.jpg").content == b"bild"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/api/me",
        "http://localhost/admin",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
    ],
)
def test_this_machine_and_its_network_are_not(url):
    with _client(lambda request: httpx.Response(200)) as client, pytest.raises(outbound.Refused):
        client.get(url)


def test_other_schemes_are_not():
    with pytest.raises(outbound.Refused):
        outbound.check(httpx.Request("GET", "file:///etc/passwd"))


def test_a_redirect_to_the_network_is_refused(monkeypatch):
    monkeypatch.setattr(outbound, "_private", lambda host: host == "10.0.0.5")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "covers.example":
            return httpx.Response(302, headers={"location": "http://10.0.0.5/secret"})
        return httpx.Response(200, content=b"internal")

    with _client(handler) as client, pytest.raises(outbound.Refused):
        client.get("https://covers.example/1.jpg")


def test_every_response_has_the_security_headers(api):
    client, _ = api
    for response in (client.get("/healthz"), client.get("/api/libraries"), client.get("/api/nothing-here")):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "same-origin"
        assert response.headers["x-frame-options"] == "SAMEORIGIN"
