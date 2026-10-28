"""Passkeys and two-step login: adding and removing passkeys, logging in
with one, and turning the authenticator app (TOTP) with its recovery codes
on and off. Changes to these need a web session, not an app's key."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from kodex.core.auth import factors, passkeys, totp
from kodex.core.auth.api import AccountOut, log_in
from kodex.core.auth.models import Passkey

router = APIRouter(tags=["auth"])


class CeremonyOut(BaseModel):
    ticket: str = Field(description="Sent back with the browser's answer; valid for five minutes.")
    options: dict[str, Any] = Field(description="WebAuthn options, as PublicKeyCredential*OptionsJSON.")


class PasskeyOut(BaseModel):
    id: int
    name: str
    backed_up: bool
    created_at: dt.datetime
    last_used_at: dt.datetime | None


class PasskeyIn(BaseModel):
    ticket: str = Field(min_length=1, max_length=64)
    credential: dict[str, Any] = Field(description="The browser's PublicKeyCredential, as JSON.")
    name: str = Field(default="", max_length=100)


class PasskeyRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class PasskeyLoginOptionsIn(BaseModel):
    ticket: str | None = Field(default=None, max_length=64, description="A password login's second-step ticket.")


class PasskeyLoginIn(BaseModel):
    ticket: str = Field(min_length=1, max_length=64)
    credential: dict[str, Any]


class TotpSetupOut(BaseModel):
    secret: str = Field(description="For typing into the app by hand.")
    uri: str = Field(description="The otpauth:// link, for a QR code.")


class CodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class RecoveryCodesOut(BaseModel):
    codes: list[str] = Field(description="Shown this once; each works once.")


def session_user(request: Request, user: User = Depends(get_current_user)) -> User:
    if getattr(request.state, "auth_method", None) not in ("session", "dev"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Change this from the web client")
    return user


def passkeys_on() -> bool:
    """Passkeys are one of Kodex's own logins: off with LOCAL_LOGIN_ENABLED too."""
    settings = get_settings()
    return settings.passkeys_enabled and settings.local_login_enabled


def _require_passkeys() -> None:
    if not passkeys_on():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passkeys are turned off")


def _view(passkey: Passkey) -> PasskeyOut:
    return PasskeyOut(id=passkey.id, name=passkey.name, backed_up=passkey.backed_up, created_at=passkey.created_at,
                      last_used_at=passkey.last_used_at)  # fmt: skip


def _own(db: Session, user: User, passkey_id: int) -> Passkey:
    passkey = db.get(Passkey, passkey_id)
    if passkey is None or passkey.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such passkey")
    return passkey


@router.get("/auth/passkeys", response_model=list[PasskeyOut])
def list_passkeys(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[PasskeyOut]:
    return [_view(p) for p in passkeys.of_user(db, user.id)]


@router.post("/auth/passkeys/options", response_model=CeremonyOut)
def passkey_options(request: Request, db: Session = Depends(get_db),
                    user: User = Depends(session_user)) -> CeremonyOut:  # fmt: skip
    """Options for navigator.credentials.create, to add a passkey."""
    _require_passkeys()
    ticket, options = passkeys.registration_options(db, user, request)
    db.commit()
    return CeremonyOut(ticket=ticket, options=json.loads(options))


@router.post("/auth/passkeys", response_model=PasskeyOut, status_code=status.HTTP_201_CREATED)
def add_passkey(body: PasskeyIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(session_user)) -> PasskeyOut:  # fmt: skip
    _require_passkeys()
    count = len(passkeys.of_user(db, user.id))
    try:
        passkey = passkeys.register(db, user, body.ticket, body.credential,
                                    body.name.strip() or f"Passkey {count + 1}", request)  # fmt: skip
    except passkeys.PasskeyError as exc:
        db.commit()  # the ticket is used up either way
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(passkey)
    return _view(passkey)


@router.patch("/auth/passkeys/{passkey_id}", response_model=PasskeyOut)
def rename_passkey(passkey_id: int, body: PasskeyRenameIn, db: Session = Depends(get_db),
                   user: User = Depends(session_user)) -> PasskeyOut:  # fmt: skip
    passkey = _own(db, user, passkey_id)
    passkey.name = body.name.strip()
    db.commit()
    return _view(passkey)


@router.delete("/auth/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_passkey(passkey_id: int, db: Session = Depends(get_db), user: User = Depends(session_user)) -> None:
    passkey = _own(db, user, passkey_id)
    others = [p for p in passkeys.of_user(db, user.id) if p.id != passkey.id]
    if not others and user.password_hash is None and user.oidc_subject is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Set a password first, or you can't log in afterwards")  # fmt: skip
    db.delete(passkey)
    db.commit()


@router.post("/auth/passkeys/login/options", response_model=CeremonyOut)
def passkey_login_options(body: PasskeyLoginOptionsIn, request: Request,
                          db: Session = Depends(get_db)) -> CeremonyOut:  # fmt: skip
    """Options for navigator.credentials.get: a login with any passkey for
    this site, or with a second-step ticket, one of that account's."""
    _require_passkeys()
    second_step = None
    if body.ticket:
        second_step = factors.ticket(db, body.ticket, ("second_factor",))
        if second_step is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="The login took too long; start again")
    ticket, options = passkeys.login_options(db, request, second_step)
    db.commit()
    return CeremonyOut(ticket=ticket, options=json.loads(options))


@router.post("/auth/passkeys/login", response_model=AccountOut)
def passkey_login(body: PasskeyLoginIn, request: Request, response: Response,
                  db: Session = Depends(get_db)) -> AccountOut:  # fmt: skip
    _require_passkeys()
    try:
        user = passkeys.authenticate(db, body.ticket, body.credential, request)
    except passkeys.PasskeyError as exc:
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    if user.disabled:
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled")
    return log_in(db, user, request, response)


@router.post("/auth/totp", response_model=TotpSetupOut)
def start_totp(db: Session = Depends(get_db), user: User = Depends(session_user)) -> TotpSetupOut:
    """A new secret for the authenticator app; two-step login is on once
    POST /auth/totp/confirm gets a code from it."""
    if factors.enabled(user):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Two-step login is on already")
    secret = factors.start_totp(user)
    db.commit()
    return TotpSetupOut(secret=secret, uri=totp.uri(secret, user.username))


@router.post("/auth/totp/confirm", response_model=RecoveryCodesOut)
def confirm_totp(body: CodeIn, db: Session = Depends(get_db), user: User = Depends(session_user)) -> RecoveryCodesOut:
    codes = factors.confirm_totp(db, user, body.code)
    if codes is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Wrong code")
    db.commit()
    return RecoveryCodesOut(codes=codes)


@router.post("/auth/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
def disable_totp(body: CodeIn, db: Session = Depends(get_db), user: User = Depends(session_user)) -> None:
    """Turns two-step login off, with a code from the app or a recovery
    code to show it's the owner."""
    if not factors.enabled(user):
        return
    if not factors.check(db, user, body.code):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Wrong code")
    factors.disable(db, user)
    db.commit()


@router.post("/auth/recovery-codes", response_model=RecoveryCodesOut)
def new_recovery_codes(body: CodeIn, db: Session = Depends(get_db),
                       user: User = Depends(session_user)) -> RecoveryCodesOut:  # fmt: skip
    """New recovery codes in place of the old ones."""
    if not factors.enabled(user):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Two-step login is off")
    if not factors.check(db, user, body.code):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Wrong code")
    codes = factors.new_recovery_codes(db, user)
    db.commit()
    return RecoveryCodesOut(codes=codes)
