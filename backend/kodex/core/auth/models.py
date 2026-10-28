"""Tables of the auth module: web sessions, personal API keys, failed
logins (for slowing down password guessing), OpenID Connect logins in
progress, passkeys, recovery codes, sign-in links, and the short-lived
challenges of logins and passkey ceremonies."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from kodex.core.db import Base


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # SHA-256 of the cookie's value: a copy of this table can't log anyone in.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    # "Remember me on this device": false keeps the cookie for the browser's
    # session only, and the session for a day while used.
    remember: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class ApiKey(Base):
    """A personal key for an app or a protocol (OPDS, KOSync, Kobo). Only
    hashes are kept: SHA-256 for bearer and HTTP Basic use, and for KOSync,
    whose clients send an MD5 of the password, the key's MD5 too (the key is
    random, so that is no weaker)."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(16))  # app | opds | kosync | kobo
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    md5: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginFailure(Base):
    __tablename__ = "login_failures"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(255), index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class OidcLogin(Base):
    """An OpenID Connect login on its way: the state the provider sends
    back, with the nonce and PKCE verifier that belong to it."""

    __tablename__ = "oidc_logins"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64))
    code_verifier: Mapped[str] = mapped_column(String(128))
    next_path: Mapped[str] = mapped_column(String(1024), default="/")
    # Set when a logged-in user links their account instead of logging in.
    link_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Passkey(Base):
    """A WebAuthn credential: a passkey on a phone or computer, or a
    security key."""

    __tablename__ = "passkeys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(BigInteger, default=0)
    transports: Mapped[list[str]] = mapped_column(JSON, default=list)
    name: Mapped[str] = mapped_column(String(100))
    # Synced between devices (iCloud Keychain, Google Password Manager, a
    # password manager), as opposed to bound to one device.
    backed_up: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecoveryCode(Base):
    """A one-time code for the second step when the authenticator app is
    gone; only its SHA-256 is kept (the codes are random)."""

    __tablename__ = "recovery_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SignInLink(Base):
    """A one-time link an admin hands out, for setting a password; only
    the token's SHA-256 is kept."""

    __tablename__ = "sign_in_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class AuthChallenge(Base):
    """A step that has to be finished within minutes, named by a random
    ticket the client sends back: a password login waiting for its second
    step, or a passkey registration or login with its WebAuthn challenge."""

    __tablename__ = "auth_challenges"

    ticket: Mapped[str] = mapped_column(String(64), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(16))  # second_factor | passkey_login | passkey_register | app_code
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    challenge: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # What the step is for, for people: an app's device name while it logs in.
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
