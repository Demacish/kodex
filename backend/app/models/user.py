from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    """A reader account: local (a password) or from OpenID Connect (its
    subject claim), or both. In dev mode (settings.auth_disabled) a single
    fallback user is used instead — see app/auth.py.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The OpenID Connect subject at the configured provider (v1: always
    # Authentik's); null for an account that isn't linked to one.
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    username: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # admin | user | guest (kodex.core.auth); is_admin follows it.
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    # argon2id; null for a user who only logs in through OIDC.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Two-step login (kodex.core.auth.factors): an authenticator app's base32
    # secret, in use from totp_enabled_at; totp_last_step stops a code from
    # being used twice.
    # Sealed with SECRET_KEY when it is set (kodex.core.sealed).
    totp_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    totp_enabled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # The random id passkeys know this account by (WebAuthn's user handle,
    # base64url), made with the first passkey.
    webauthn_handle: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    # Personal Send-to-Kindle address. The sender address that mails to it
    # still needs a one-time manual approval on Amazon's side (see the
    # architecture plan's "Send-to-Device" section).
    kindle_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # A long-lived, per-user secret used ONLY for OPDS access (see
    # kodex/delivery/opds). OPDS reader apps (Chunky, KyBook, Panels,
    # Moon+ Reader, ...) authenticate with HTTP Basic and don't do OAuth/
    # OIDC flows, so they can't use the bearer tokens the web app uses.
    # Generated on demand via POST /me/opds-token; the HTTP Basic
    # "password" must match this (the username is not checked).
    opds_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    # ReadMeABook-inspired configurable homepage sections (see claude/
    # omnibus-och-ai-forbattringar.md's "Övriga UX-idéer" — home-sections.md).
    # An ordered list of app/schemas/user.py's HOME_SECTION_KEYS the user
    # wants visible, in display order; a key left out is hidden. Null (the
    # default for every existing user) means "no customization yet" — the
    # frontend falls back to HOME_SECTION_KEYS' own order, all visible.
    # THIS COLUMN NEEDS A MANUAL `ALTER TABLE users ADD COLUMN
    # home_sections JSON;` ON THE PRODUCTION DATABASE — no Alembic yet,
    # same situation as every other column added to an existing table in
    # this project (see claude/forbattringar-serier-samlingar.md's
    # "Driftsättning" section).
    home_sections: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # The ntfy topic this user gets push notifications on (a new volume in a
    # followed series — see kodex/delivery/notify.py's
    # notify_new_books). Null = no push. Added via app/migrations.py.
    ntfy_topic: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} username={self.username!r}>"
