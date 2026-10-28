"""Passkeys (WebAuthn, with py_webauthn): adding one to an account, and
logging in with one, either instead of a password (a discoverable
credential, with the device's own check of who is holding it: fingerprint,
face or PIN) or as the second step after a password.

A passkey belongs to a host name (the relying party): PUBLIC_APP_URL's when
it is set, otherwise the one the browser used. Moving Kodex to another
host name leaves the passkeys behind; passwords and the provider still
work."""

from __future__ import annotations

import datetime as dt
import secrets
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import get_settings
from app.models.user import User
from kodex.core.auth import factors
from kodex.core.auth.models import AuthChallenge, Passkey

_TRANSPORTS = {t.value for t in AuthenticatorTransport}


class PasskeyError(Exception):
    """The passkey can't be used; the message says why."""


def relying_party(request: Request) -> tuple[str, str]:
    """The passkeys' host name (WebAuthn's RP ID) and the origin the
    browser must report."""
    public = get_settings().public_app_url.rstrip("/")
    if public:
        parts = urlsplit(public)
        return parts.hostname or "", f"{parts.scheme}://{parts.netloc}"
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("host") or request.url.netloc
    return urlsplit(f"//{host}").hostname or "", f"{proto}://{host}"


def _descriptors(passkeys: list[Passkey]) -> list[PublicKeyCredentialDescriptor]:
    return [PublicKeyCredentialDescriptor(id=p.credential_id,
                                          transports=[AuthenticatorTransport(t) for t in p.transports if t in _TRANSPORTS])
            for p in passkeys]  # fmt: skip


def of_user(db: Session, user_id: int) -> list[Passkey]:
    return list(db.scalars(select(Passkey).where(Passkey.user_id == user_id).order_by(Passkey.created_at)).all())


def registration_options(db: Session, user: User, request: Request) -> tuple[str, str]:
    """A ticket and the options (JSON) for navigator.credentials.create."""
    if user.webauthn_handle is None:
        user.webauthn_handle = bytes_to_base64url(secrets.token_bytes(32))
    rp_id, _ = relying_party(request)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name="Kodex",
        user_id=base64url_to_bytes(user.webauthn_handle),
        user_name=user.username,
        user_display_name=user.username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.PREFERRED
        ),
        exclude_credentials=_descriptors(of_user(db, user.id)),
    )
    row = factors.new_ticket(db, "passkey_register", user.id, options.challenge)
    return row.ticket, options_to_json(options)


def register(db: Session, user: User, ticket: str, credential: dict[str, Any], name: str, request: Request) -> Passkey:
    row = factors.take(db, ticket, ("passkey_register",))
    if row is None or row.user_id != user.id or row.challenge is None:
        raise PasskeyError("The passkey took too long; try again")
    rp_id, origin = relying_party(request)
    try:
        verified = verify_registration_response(credential=credential, expected_challenge=row.challenge,
                                                expected_rp_id=rp_id, expected_origin=origin)  # fmt: skip
    except WebAuthnException as exc:
        raise PasskeyError(f"The passkey could not be verified: {exc}") from exc
    if db.scalars(select(Passkey.id).where(Passkey.credential_id == verified.credential_id)).first() is not None:
        raise PasskeyError("This passkey is added already")
    transports = (credential.get("response") or {}).get("transports") or []
    passkey = Passkey(user_id=user.id, credential_id=verified.credential_id, public_key=verified.credential_public_key,
                      sign_count=verified.sign_count, transports=[t for t in transports if t in _TRANSPORTS],
                      name=name, backed_up=verified.credential_backed_up)  # fmt: skip
    db.add(passkey)
    db.flush()
    return passkey


def login_options(db: Session, request: Request, second_step: AuthChallenge | None = None) -> tuple[str, str]:
    """A ticket and the options (JSON) for navigator.credentials.get: any
    passkey for this site, with the device checking who holds it, or, as
    the second step of a password login, one of that user's."""
    rp_id, _ = relying_party(request)
    if second_step is not None and second_step.user_id is not None:
        options = generate_authentication_options(rp_id=rp_id, allow_credentials=_descriptors(of_user(db, second_step.user_id)),
                                                  user_verification=UserVerificationRequirement.PREFERRED)  # fmt: skip
        second_step.challenge = options.challenge
        return second_step.ticket, options_to_json(options)
    options = generate_authentication_options(rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED)
    return factors.new_ticket(db, "passkey_login", None, options.challenge).ticket, options_to_json(options)


def authenticate(db: Session, ticket: str, credential: dict[str, Any], request: Request) -> User:
    """The user a passkey login stands for; the ticket is used up."""
    row = factors.take(db, ticket, ("passkey_login", "second_factor"))
    if row is None or row.challenge is None:
        raise PasskeyError("The login took too long; try again")
    try:
        raw_id = base64url_to_bytes(str(credential.get("rawId") or credential.get("id") or ""))
    except ValueError as exc:
        raise PasskeyError("That is not a passkey") from exc
    passkey = db.scalars(select(Passkey).where(Passkey.credential_id == raw_id)).first()
    if passkey is None or (row.user_id is not None and passkey.user_id != row.user_id):
        raise PasskeyError("This passkey isn't known here")
    user = db.get(User, passkey.user_id)
    if user is None:
        raise PasskeyError("This passkey isn't known here")
    handle = (credential.get("response") or {}).get("userHandle")
    if handle and handle != user.webauthn_handle:
        raise PasskeyError("This passkey isn't known here")
    rp_id, origin = relying_party(request)
    try:
        verified = verify_authentication_response(
            credential=credential, expected_challenge=row.challenge, expected_rp_id=rp_id, expected_origin=origin,
            credential_public_key=passkey.public_key, credential_current_sign_count=passkey.sign_count,
            require_user_verification=row.purpose == "passkey_login",
        )  # fmt: skip
    except WebAuthnException as exc:
        raise PasskeyError(f"The passkey could not be verified: {exc}") from exc
    passkey.sign_count = verified.new_sign_count
    passkey.backed_up = verified.credential_backed_up
    passkey.last_used_at = dt.datetime.now(dt.UTC)
    return user
