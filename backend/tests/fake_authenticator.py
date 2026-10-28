"""A passkey authenticator in software, for tests: it answers WebAuthn
options the way a browser hands them to a phone or security key, with a
P-256 key, "none" attestation and real signatures."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

UP, UV, BE, BS, AT = 0x01, 0x04, 0x08, 0x10, 0x40


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class FakeAuthenticator:
    def __init__(self, origin: str = "https://kodex.test") -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(16)
        self.origin = origin
        self.sign_count = 0
        self.user_handle: str | None = None

    def _public_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def _client_data(self, kind: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin or self.origin,
                           "crossOrigin": False}).encode()  # fmt: skip

    def _ids(self) -> dict[str, str]:
        return {"id": b64url(self.credential_id), "rawId": b64url(self.credential_id), "type": "public-key"}

    def create(self, options: dict[str, Any], *, flags: int = UP | UV | BE | BS, origin: str | None = None) -> dict:
        self.user_handle = options["user"]["id"]
        rp_hash = hashlib.sha256(options["rp"]["id"].encode()).digest()
        attested = bytes(16) + len(self.credential_id).to_bytes(2, "big") + self.credential_id + self._public_key()
        auth_data = rp_hash + bytes([flags | AT]) + self.sign_count.to_bytes(4, "big") + attested
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        return {**self._ids(), "authenticatorAttachment": "platform", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64url(client_data), "attestationObject": b64url(attestation),
                             "transports": ["internal", "hybrid"]}}  # fmt: skip

    def get(self, options: dict[str, Any], *, flags: int = UP | UV | BE | BS, origin: str | None = None) -> dict:
        self.sign_count += 1
        rp_hash = hashlib.sha256(options["rpId"].encode()).digest()
        auth_data = rp_hash + bytes([flags]) + self.sign_count.to_bytes(4, "big")
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {**self._ids(), "authenticatorAttachment": "platform", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64url(client_data), "authenticatorData": b64url(auth_data),
                             "signature": b64url(signature), "userHandle": self.user_handle}}  # fmt: skip
