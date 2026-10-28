"""Logging an app in (the Android app): it gets a personal API key of its
own, named after the device, which the user can see and revoke under
Inställningar. Two ways in:

- with the password, and the app's code or a recovery code when two-step
  login is on (``/auth/app/login``, ``/auth/app/second-step``);
- through the browser, for passkeys or the identity provider: the app
  opens ``/app-login`` in a browser tab with a PKCE-style challenge, the
  logged-in user approves, and the app trades the code it gets back at
  ``kodex://login`` and its verifier for the key (``/auth/app/token``).
  The code works once, for five minutes, and only with the verifier."""

from __future__ import annotations

import base64
import hashlib
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from kodex.core.auth import factors, keys, passwords, throttle
from kodex.core.auth.api import SecondStepOut, _local_user
from kodex.core.auth.models import ApiKey

router = APIRouter(tags=["auth"])


class AppLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)
    device_name: str = Field(min_length=1, max_length=80)


class AppKeyOut(BaseModel):
    id: int
    name: str
    key: str = Field(description="The app's bearer token; shown this once.")


class AppLoginOut(BaseModel):
    """The key, or the second step the account still needs."""

    key: AppKeyOut | None = None
    second_step: SecondStepOut | None = None


class AppSecondStepIn(BaseModel):
    ticket: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=32)


class AppApproveIn(BaseModel):
    device_name: str = Field(min_length=1, max_length=80)
    challenge: str = Field(min_length=43, max_length=128, description="base64url SHA-256 of the app's verifier")


class AppApproveOut(BaseModel):
    code: str


class AppTokenIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    verifier: str = Field(min_length=43, max_length=128)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _issue(db: Session, user: User, device_name: str) -> AppKeyOut:
    record, key = keys.create(db, user, f"App: {device_name.strip()}"[:100], "app")
    db.commit()
    return AppKeyOut(id=record.id, name=record.name, key=key)


def _refused(detail: str, code: int = status.HTTP_401_UNAUTHORIZED) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


@router.post("/auth/app/login", response_model=AppLoginOut)
def app_login(body: AppLoginIn, request: Request, db: Session = Depends(get_db)) -> AppLoginOut:
    if not get_settings().local_login_enabled:
        raise _refused("Password login is turned off", status.HTTP_403_FORBIDDEN)
    wait = throttle.seconds_to_wait(db, body.username, _ip(request))
    if wait:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed logins",
                            headers={"Retry-After": str(wait)})  # fmt: skip
    user = _local_user(db, body.username)
    if not passwords.verify_password(user.password_hash if user else None, body.password) or user is None:
        throttle.record_failure(db, body.username, _ip(request))
        raise _refused("Wrong username or password")
    if user.disabled:
        raise _refused("This account is disabled", status.HTTP_403_FORBIDDEN)
    throttle.clear(db, body.username)
    if not factors.enabled(user):
        return AppLoginOut(key=_issue(db, user, body.device_name))
    ticket = factors.new_ticket(db, "second_factor", user.id)
    ticket.label = body.device_name.strip()[:100]
    db.commit()
    return AppLoginOut(second_step=SecondStepOut(ticket=ticket.ticket, methods=["totp", "recovery"]))


@router.post("/auth/app/second-step", response_model=AppKeyOut)
def app_second_step(body: AppSecondStepIn, request: Request, db: Session = Depends(get_db)) -> AppKeyOut:
    ticket = factors.ticket(db, body.ticket, ("second_factor",))
    user = db.get(User, ticket.user_id) if ticket is not None and ticket.user_id is not None else None
    if ticket is None or user is None or not ticket.label:
        raise _refused("The login took too long; start again")
    if user.disabled:
        raise _refused("This account is disabled", status.HTTP_403_FORBIDDEN)
    if not factors.check(db, user, body.code):
        ticket.attempts += 1
        if ticket.attempts >= factors.MAX_ATTEMPTS:
            db.delete(ticket)
        db.commit()
        throttle.record_failure(db, user.username, _ip(request))
        raise _refused("Wrong code")
    device = ticket.label
    db.delete(ticket)
    return _issue(db, user, device)


@router.post("/auth/app/approve", response_model=AppApproveOut)
def app_approve(body: AppApproveIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> AppApproveOut:  # fmt: skip
    """The logged-in user lets an app on a device in: a one-time code for
    the app, bound to its challenge."""
    if getattr(request.state, "auth_method", None) not in ("session", "dev"):
        raise _refused("Approve the app from the web client", status.HTTP_403_FORBIDDEN)
    try:
        challenge = base64.urlsafe_b64decode(body.challenge + "=" * (-len(body.challenge) % 4))
    except ValueError as exc:
        raise _refused("The challenge isn't base64url", status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    if len(challenge) != 32:
        raise _refused("The challenge isn't a SHA-256", status.HTTP_422_UNPROCESSABLE_CONTENT)
    ticket = factors.new_ticket(db, "app_code", user.id, challenge)
    ticket.label = body.device_name.strip()[:100]
    db.commit()
    return AppApproveOut(code=ticket.ticket)


@router.post("/auth/app/token", response_model=AppKeyOut)
def app_token(body: AppTokenIn, db: Session = Depends(get_db)) -> AppKeyOut:
    """The key for an approved app, in exchange for its code and verifier."""
    ticket = factors.take(db, body.code, ("app_code",))
    if ticket is None or ticket.challenge is None or ticket.user_id is None:
        db.commit()
        raise _refused("The code is used, expired or wrong")
    sent = hashlib.sha256(body.verifier.encode()).digest()
    user = db.get(User, ticket.user_id)
    if not hmac.compare_digest(sent, ticket.challenge) or user is None or user.disabled:
        db.commit()
        raise _refused("The code is used, expired or wrong")
    return _issue(db, user, ticket.label or "App")


@router.post("/auth/app/logout", status_code=status.HTTP_204_NO_CONTENT)
def app_logout(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    """Revokes the key the app called with."""
    key_id = getattr(request.state, "api_key_id", None)
    if key_id is None:
        raise _refused("Only an app's key logs out here", status.HTTP_400_BAD_REQUEST)
    record = db.get(ApiKey, key_id)
    if record is not None and record.user_id == user.id:
        db.delete(record)
        db.commit()
