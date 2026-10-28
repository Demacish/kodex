"""The auth endpoints: login (password, with its second step when the
account has one, or OpenID Connect), the first admin, the current account
and its sessions, linking a provider account, personal API keys, sign-in
links, and user management for admins. Passkeys and two-step login are
kodex.core.auth.factors_api."""

from __future__ import annotations

import datetime as dt
from typing import Literal
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

import kodex
from app.auth import check_claims, get_current_user, require_admin, user_from_claims
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from kodex.core.auth import factors, keys, links, oidc, passwords, sessions, throttle
from kodex.core.auth import setup as first_admin
from kodex.core.auth.models import ApiKey, Passkey, UserSession
from kodex.core.auth.roles import set_role

router = APIRouter(tags=["auth"])

Role = Literal["admin", "user", "guest"]
Purpose = Literal["app", "opds", "kosync", "kobo"]
_SETUP_LOCK = 0x6B6F646578  # pg_advisory_xact_lock key for creating the first admin
_FORGET = "forget"  # a second-step ticket's label: the login isn't to be remembered


class AuthConfig(BaseModel):
    local_login: bool
    passkeys: bool
    oidc: bool
    oidc_name: str
    setup_required: bool = Field(description="The first visit chooses the admin (POST /auth/setup).")
    setup_code_required: bool = Field(
        default=False,
        description="The server has accounts but no admin who can log in: setting one up takes the code "
        "the api wrote to its log when it started.",
    )
    auth_disabled: bool
    version: str = Field(
        default=kodex.__version__, description="The server's version; a web client older or newer reloads."
    )


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)
    remember: bool = Field(default=True, description="Keep the login after the browser closes.")


class SetupIn(LoginIn):
    email: str | None = Field(default=None, max_length=255)
    code: str | None = Field(default=None, max_length=32, description="The setup code, when the config asks for it.")


class AccountOut(BaseModel):
    id: int
    username: str
    email: str | None
    role: str
    is_admin: bool
    has_password: bool
    oidc: bool
    two_factor: bool
    passkeys: int
    recovery_codes_left: int
    auth_method: str
    csrf_token: str | None = None


class SecondStepOut(BaseModel):
    ticket: str = Field(description="Sent back with the code or passkey; valid for five minutes.")
    methods: list[Literal["totp", "recovery", "passkey"]]


class LoginOut(BaseModel):
    """Either the account, logged in, or the second step it still needs."""

    account: AccountOut | None = None
    second_step: SecondStepOut | None = None


class SecondStepIn(BaseModel):
    ticket: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=32, description="The app's six digits, or a recovery code.")


class SignInLinkOut(BaseModel):
    url: str
    expires_at: dt.datetime


class SignInLinkCheckIn(BaseModel):
    token: str = Field(min_length=1, max_length=128)


class SignInLinkCheckOut(BaseModel):
    username: str


class SignInLinkIn(SignInLinkCheckIn):
    password: str = Field(min_length=1, max_length=1024)


class OidcLinkOut(BaseModel):
    url: str


class PasswordIn(BaseModel):
    current_password: str | None = Field(default=None, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class SessionOut(BaseModel):
    id: int
    user_agent: str | None
    created_at: dt.datetime
    last_seen_at: dt.datetime
    current: bool


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    purpose: Purpose


class ApiKeyOut(BaseModel):
    id: int
    name: str
    purpose: str
    prefix: str
    created_at: dt.datetime
    last_used_at: dt.datetime | None


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(description="Shown this once; only a hash is kept.")


class UserAdminOut(BaseModel):
    id: int
    username: str
    email: str | None
    role: str
    disabled: bool
    has_password: bool
    oidc: bool
    two_factor: bool
    passkeys: int
    created_at: dt.datetime
    last_login_at: dt.datetime | None


class UserCreateIn(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    role: Role = "user"
    password: str | None = Field(default=None, max_length=1024)


class UserUpdateIn(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    role: Role | None = None
    disabled: bool | None = None
    password: str | None = Field(default=None, max_length=1024)


def _passkey_count(db: Session, user_id: int) -> int:
    return int(db.scalar(select(func.count()).where(Passkey.user_id == user_id)) or 0)


def account_view(db: Session, user: User, request: Request, csrf_token: str | None = None) -> AccountOut:
    session = getattr(request.state, "session", None)
    return AccountOut(id=user.id, username=user.username, email=user.email, role=user.role, is_admin=user.is_admin,
                      has_password=user.password_hash is not None, oidc=user.oidc_subject is not None,
                      two_factor=factors.enabled(user), passkeys=_passkey_count(db, user.id),
                      recovery_codes_left=factors.recovery_codes_left(db, user.id) if factors.enabled(user) else 0,
                      auth_method=getattr(request.state, "auth_method", "session"),
                      csrf_token=csrf_token or (session.csrf_token if session is not None else None))  # fmt: skip


def _admin_view(db: Session, user: User) -> UserAdminOut:
    return UserAdminOut(id=user.id, username=user.username, email=user.email, role=user.role, disabled=user.disabled,
                        has_password=user.password_hash is not None, oidc=user.oidc_subject is not None,
                        two_factor=factors.enabled(user), passkeys=_passkey_count(db, user.id),
                        created_at=user.created_at, last_login_at=user.last_login_at)  # fmt: skip


def log_in(db: Session, user: User, request: Request, response: Response, *, remember: bool = True) -> AccountOut:
    """Starts a session for ``user`` (whose login is complete)."""
    sessions.forget(db, request)
    session = sessions.start(db, user, request, response, remember=remember)
    db.commit()
    request.state.auth_method = "session"
    return account_view(db, user, request, session.csrf_token)


def _after_password(db: Session, user: User, request: Request, response: Response, *,
                    remember: bool = True) -> LoginOut:  # fmt: skip
    """The password was right: logged in, or on to the second step (whose
    ticket keeps ``remember`` in its label)."""
    if not factors.enabled(user):
        return LoginOut(account=log_in(db, user, request, response, remember=remember))
    methods: list[Literal["totp", "recovery", "passkey"]] = ["totp", "recovery"]
    if get_settings().passkeys_enabled and _passkey_count(db, user.id):
        methods.append("passkey")
    ticket = factors.new_ticket(db, "second_factor", user.id)
    ticket.label = None if remember else _FORGET
    db.commit()
    return LoginOut(second_step=SecondStepOut(ticket=ticket.ticket, methods=methods))


def public_url(request: Request, path: str) -> str:
    base = get_settings().public_app_url.rstrip("/") or str(request.base_url).rstrip("/")
    return base + path


def _check_password(password: str) -> None:
    problem = passwords.check_strength(password)
    if problem:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Password needs {problem}")


def _username_taken(db: Session, username: str, *, except_id: int | None = None) -> bool:
    query = select(User.id).where(func.lower(User.username) == username.lower())
    if except_id is not None:
        query = query.where(User.id != except_id)
    return db.scalars(query).first() is not None


def _local_user(db: Session, username: str) -> User | None:
    query = select(User).where(func.lower(User.username) == username.lower(), User.password_hash.isnot(None))
    return db.scalars(query.order_by(User.id)).first()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/auth/config", response_model=AuthConfig)
def auth_config(db: Session = Depends(get_db)) -> AuthConfig:
    settings = get_settings()
    setup = first_admin.state(db)
    return AuthConfig(local_login=settings.local_login_enabled,
                      passkeys=settings.passkeys_enabled and settings.local_login_enabled, oidc=oidc.enabled(),
                      oidc_name=settings.oidc_display_name, setup_required=setup != "ready",
                      setup_code_required=setup == "claim", auth_disabled=settings.auth_disabled)  # fmt: skip


@router.post("/auth/setup", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def setup(body: SetupIn, request: Request, response: Response, db: Session = Depends(get_db)) -> AccountOut:
    """Sets up the first admin: on a server without users, a new account; on
    one whose admins can't log in, with the setup code from the api's log,
    that account (if it exists, it gets the password and stays as it is
    otherwise) or a new one."""
    _check_password(body.password)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SETUP_LOCK})
    current = first_admin.state(db)
    if current == "ready":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This server already has an admin")
    username = body.username.strip()
    user: User | None = None
    if current == "claim":
        wait = throttle.seconds_to_wait(db, first_admin.THROTTLE_KEY, _ip(request))
        if wait:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many wrong setup codes",
                                headers={"Retry-After": str(wait)})  # fmt: skip
        if not first_admin.check_code(body.code or ""):
            throttle.record_failure(db, first_admin.THROTTLE_KEY, _ip(request))
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Wrong setup code")
        query = select(User).where(func.lower(User.username) == username.lower()).order_by(User.id)
        user = db.scalars(query).first()
        if user is not None and user.password_hash is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="That account already has a password: log in with it")  # fmt: skip
        if user is not None and user.disabled:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That account is disabled")
        throttle.clear(db, first_admin.THROTTLE_KEY)
    if user is None:
        user = User(username=username, email=body.email)
        db.add(user)
    elif body.email and not user.email:
        user.email = body.email
    user.password_hash = passwords.hash_password(body.password)
    set_role(user, "admin")
    db.flush()
    first_admin.forget_code()
    session = sessions.start(db, user, request, response, remember=body.remember)
    db.commit()
    request.state.auth_method = "session"
    return account_view(db, user, request, session.csrf_token)


@router.post("/auth/login", response_model=LoginOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> LoginOut:
    """A password login. With two-step login on, the answer is a ticket for
    POST /auth/login/second-step (or a passkey) instead of the account."""
    if not get_settings().local_login_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password login is turned off")
    wait = throttle.seconds_to_wait(db, body.username, _ip(request))
    if wait:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed logins",
                            headers={"Retry-After": str(wait)})  # fmt: skip
    user = _local_user(db, body.username)
    if not passwords.verify_password(user.password_hash if user else None, body.password) or user is None:
        throttle.record_failure(db, body.username, _ip(request))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong username or password")
    if user.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled")
    if passwords.needs_rehash(user.password_hash or ""):
        user.password_hash = passwords.hash_password(body.password)
    throttle.clear(db, body.username)
    return _after_password(db, user, request, response, remember=body.remember)


@router.post("/auth/login/second-step", response_model=AccountOut)
def second_step(body: SecondStepIn, request: Request, response: Response, db: Session = Depends(get_db)) -> AccountOut:
    """Finishes a password login with the authenticator app's code or a
    recovery code."""
    ticket = factors.ticket(db, body.ticket, ("second_factor",))
    user = db.get(User, ticket.user_id) if ticket is not None and ticket.user_id is not None else None
    if ticket is None or user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="The login took too long; start again")
    wait = throttle.seconds_to_wait(db, user.username, _ip(request))
    if wait:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed logins",
                            headers={"Retry-After": str(wait)})  # fmt: skip
    if user.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled")
    if not factors.check(db, user, body.code):
        ticket.attempts += 1
        if ticket.attempts >= factors.MAX_ATTEMPTS:
            db.delete(ticket)
        db.commit()
        throttle.record_failure(db, user.username, _ip(request))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong code")
    remember = ticket.label != _FORGET
    db.delete(ticket)
    throttle.clear(db, user.username)
    return log_in(db, user, request, response, remember=remember)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    sessions.current(db, request)  # refuses a request without the CSRF token
    sessions.end(db, request, response)
    db.commit()


@router.get("/auth/me", response_model=AccountOut)
def me(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AccountOut:
    return account_view(db, user, request)


@router.post("/auth/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)) -> None:  # fmt: skip
    if user.password_hash is not None and not passwords.verify_password(
        user.password_hash, body.current_password or ""
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The current password is wrong")
    _check_password(body.new_password)
    if user.password_hash is None and _local_user(db, user.username) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Another account has this username")
    user.password_hash = passwords.hash_password(body.new_password)
    current = getattr(request.state, "session", None)
    sessions.end_all(db, user.id, except_id=current.id if current is not None else None)
    db.commit()


@router.get("/auth/sessions", response_model=list[SessionOut])
def list_sessions(request: Request, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)) -> list[SessionOut]:  # fmt: skip
    current = getattr(request.state, "session", None)
    rows = db.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.expires_at > func.now())
                      .order_by(UserSession.last_seen_at.desc())).all()  # fmt: skip
    return [SessionOut(id=s.id, user_agent=s.user_agent, created_at=s.created_at, last_seen_at=s.last_seen_at,
                       current=current is not None and s.id == current.id) for s in rows]  # fmt: skip


@router.delete("/auth/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def end_session(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    session = db.get(UserSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such session")
    db.delete(session)
    db.commit()


def _safe_next(path: str | None) -> str:
    if not path or not path.startswith("/") or path.startswith(("//", "/\\")) or urlsplit(path).netloc:
        return "/"
    return path[:1024]


def _callback_url(request: Request) -> str:
    url = str(request.url_for("oidc_callback"))
    public = get_settings().public_app_url.rstrip("/")
    if public:
        parts = urlsplit(url)
        url = public + parts.path
    return url


def _login_error(message: str) -> RedirectResponse:
    return RedirectResponse(f"/login?error={quote(message)}", status_code=status.HTTP_303_SEE_OTHER)


def _settings_redirect(problem: str | None = None) -> RedirectResponse:
    target = f"/settings?link_error={quote(problem)}" if problem else "/settings?linked=1"
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


def _require_oidc() -> None:
    if not oidc.enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OpenID Connect isn't set up")


@router.get("/auth/oidc/login", name="oidc_login")
def oidc_login(request: Request, next: str | None = Query(default=None), db: Session = Depends(get_db)) -> Response:
    _require_oidc()
    try:
        target = oidc.begin(db, _callback_url(request), _safe_next(next))
    except oidc.OidcError as exc:
        return _login_error(str(exc))
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/auth/oidc/link", response_model=OidcLinkOut)
def oidc_link(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> OidcLinkOut:
    """Where to send the browser to link this account to the provider's:
    after that, either login reaches the same account."""
    _require_oidc()
    if getattr(request.state, "auth_method", None) != "session":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Link the provider from the web client")
    try:
        return OidcLinkOut(url=oidc.begin(db, _callback_url(request), "/settings", link_user_id=user.id))
    except oidc.OidcError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.delete("/auth/oidc/link", status_code=status.HTTP_204_NO_CONTENT)
def oidc_unlink(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    if user.oidc_subject is None:
        return
    if user.password_hash is None and _passkey_count(db, user.id) == 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Set a password or add a passkey first, or you can't log in afterwards")  # fmt: skip
    user.oidc_subject = None
    db.commit()


def _link(db: Session, request: Request, user_id: int, claims: dict[str, object]) -> RedirectResponse:
    found = sessions.current(db, request)
    if found is None or found[1].id != user_id:
        return _settings_redirect("Log in to Kodex again, then link the account")
    user = found[1]
    try:
        check_claims(claims)
    except HTTPException as exc:
        return _settings_redirect(str(exc.detail))
    subject = str(claims["sub"])
    taken = db.scalars(select(User.id).where(User.oidc_subject == subject, User.id != user.id)).first()
    if taken is not None:
        return _settings_redirect("That login belongs to another Kodex account")
    user.oidc_subject = subject
    if user.email is None and isinstance(claims.get("email"), str):
        user.email = str(claims["email"])
    db.commit()
    return _settings_redirect()


@router.get("/auth/oidc/callback", name="oidc_callback")
def oidc_callback(request: Request, state: str = "", code: str = "", error: str | None = None,
                  db: Session = Depends(get_db)) -> Response:  # fmt: skip
    if error:
        return _login_error(error)
    try:
        claims, next_path, link_user_id = oidc.finish(db, state, code, _callback_url(request))
        if link_user_id is not None:
            return _link(db, request, link_user_id, claims)
        user = user_from_claims(db, claims)
    except oidc.OidcError as exc:
        return _login_error(str(exc))
    except HTTPException as exc:
        return _login_error(str(exc.detail))
    response = RedirectResponse(_safe_next(next_path), status_code=status.HTTP_303_SEE_OTHER)
    sessions.forget(db, request)
    sessions.start(db, user, request, response)
    db.commit()
    return response


@router.post("/auth/sign-in-link/check", response_model=SignInLinkCheckOut)
def check_sign_in_link(body: SignInLinkCheckIn, db: Session = Depends(get_db)) -> SignInLinkCheckOut:
    """Whose a sign-in link is, before its password is chosen."""
    user = links.user_for(db, body.token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The link is used, expired or wrong")
    return SignInLinkCheckOut(username=user.username)


@router.post("/auth/sign-in-link", response_model=LoginOut)
def use_sign_in_link(body: SignInLinkIn, request: Request, response: Response,
                     db: Session = Depends(get_db)) -> LoginOut:  # fmt: skip
    """Sets the password a sign-in link was for, and logs in (with the
    second step, when the account has one)."""
    _check_password(body.password)
    user = links.use(db, body.token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The link is used, expired or wrong")
    if _local_user(db, user.username) not in (None, user):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Another account has this username")
    user.password_hash = passwords.hash_password(body.password)
    sessions.end_all(db, user.id)
    return _after_password(db, user, request, response)


def _key_view(record: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(id=record.id, name=record.name, purpose=record.purpose, prefix=record.prefix,
                     created_at=record.created_at, last_used_at=record.last_used_at)  # fmt: skip


@router.get("/me/api-keys", response_model=list[ApiKeyOut])
def list_api_keys(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ApiKeyOut]:
    rows = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())).all()
    return [_key_view(r) for r in rows]


@router.post("/me/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
def create_api_key(
    body: ApiKeyIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ApiKeyCreated:
    record, key = keys.create(db, user, body.name.strip(), body.purpose)
    if body.purpose == "kobo":
        from kodex.reading.kobo.api import device_for

        device_for(db, record, user)
    db.commit()
    db.refresh(record)
    return ApiKeyCreated(**_key_view(record).model_dump(), key=key)


@router.delete("/me/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    record = db.get(ApiKey, key_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such key")
    db.delete(record)
    db.commit()


@router.get("/admin/users", response_model=list[UserAdminOut])
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> list[UserAdminOut]:
    return [_admin_view(db, u) for u in db.scalars(select(User).order_by(func.lower(User.username))).all()]


@router.post("/admin/users", response_model=UserAdminOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreateIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> UserAdminOut:
    username = body.username.strip()
    if _username_taken(db, username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That username is taken")
    user = User(username=username, email=body.email)
    if body.password is not None:
        _check_password(body.password)
        user.password_hash = passwords.hash_password(body.password)
    set_role(user, body.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _admin_view(db, user)


@router.post("/admin/users/{user_id}/sign-in-link", response_model=SignInLinkOut)
def create_sign_in_link(user_id: int, request: Request, db: Session = Depends(get_db),
                        _admin: User = Depends(require_admin)) -> SignInLinkOut:  # fmt: skip
    """A one-time link (three days) with which the user sets a password;
    hand it over yourself. A new link replaces the last one."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user")
    token, expires = links.create(db, user)
    db.commit()
    return SignInLinkOut(url=public_url(request, f"/welcome#{token}"), expires_at=expires)


@router.post("/admin/users/{user_id}/reset-two-factor", response_model=UserAdminOut)
def reset_two_factor(user_id: int, db: Session = Depends(get_db),
                     _admin: User = Depends(require_admin)) -> UserAdminOut:  # fmt: skip
    """For a user whose phone is gone: turns two-step login off and removes
    their passkeys, and logs them out everywhere."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user")
    factors.disable(db, user)
    db.execute(delete(Passkey).where(Passkey.user_id == user.id))
    sessions.end_all(db, user.id)
    db.commit()
    db.refresh(user)
    return _admin_view(db, user)


def _other_admins(db: Session, user_id: int) -> int:
    query = select(func.count()).where(User.role == "admin", User.disabled.is_(False), User.id != user_id)
    return int(db.scalar(query) or 0)


@router.patch("/admin/users/{user_id}", response_model=UserAdminOut)
def update_user(user_id: int, body: UserUpdateIn, db: Session = Depends(get_db),
                _admin: User = Depends(require_admin)) -> UserAdminOut:  # fmt: skip
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user")
    losing_admin = user.role == "admin" and ((body.role is not None and body.role != "admin") or body.disabled)
    if losing_admin and _other_admins(db, user.id) == 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The last admin must stay an admin")
    if "email" in body.model_fields_set:
        user.email = body.email
    if body.role is not None:
        set_role(user, body.role)
    if body.disabled is not None:
        user.disabled = body.disabled
        if body.disabled:
            sessions.end_all(db, user.id)
    if body.password is not None:
        _check_password(body.password)
        if user.password_hash is None and _local_user(db, user.username) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Another account has this username")
        user.password_hash = passwords.hash_password(body.password)
        sessions.end_all(db, user.id)
    db.commit()
    db.refresh(user)
    return _admin_view(db, user)
