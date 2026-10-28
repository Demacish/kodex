"""Accounts from the command line, for the first login on a server whose
users came from v1 (they have no passwords), or when the admin is locked
out:

    python -m kodex.core.auth.cli list
    python -m kodex.core.auth.cli set-password USERNAME [--role admin] [--create]
    python -m kodex.core.auth.cli reset-two-factor USERNAME
    python -m kodex.core.auth.cli sign-in-link USERNAME

The password is asked for twice, or read from standard input with
``--password-stdin``.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import User
from kodex.core.auth import factors, links, passwords, sessions
from kodex.core.auth.models import Passkey
from kodex.core.auth.roles import ROLES, set_role
from kodex.core.db import SessionLocal


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("New password: ")
    if getpass.getpass("Again: ") != first:
        raise SystemExit("The passwords differ")
    return first


def _list() -> int:
    with SessionLocal() as db:
        for user in db.scalars(select(User).order_by(User.id)):
            kinds = (("password", user.password_hash), ("oidc", user.oidc_subject), ("two-step", factors.enabled(user)))
            kind = ", ".join(k for k, on in kinds if on)
            state = " (disabled)" if user.disabled else ""
            print(f"{user.id}\t{user.username}\t{user.role}\t{kind or '-'}{state}")
    return 0


def _find(db: Session, username: str) -> User | None:
    matches = db.scalars(select(User).where(func.lower(User.username) == username.lower())).all()
    if len(matches) > 1:
        raise SystemExit(f"{len(matches)} users are called {username!r}; rename one first")
    return matches[0] if matches else None


def _reset_two_factor(username: str) -> int:
    """For a locked-out user: two-step login off and passkeys removed."""
    with SessionLocal() as db:
        user = _find(db, username)
        if user is None:
            raise SystemExit(f"No user {username!r}")
        factors.disable(db, user)
        db.execute(delete(Passkey).where(Passkey.user_id == user.id))
        sessions.end_all(db, user.id)
        db.commit()
        print(f"{user.username}: two-step login off, passkeys removed")
    return 0


def _sign_in_link(username: str) -> int:
    """A one-time link for choosing a password (PUBLIC_APP_URL's address):
    the way into a server whose users came from v1 without asking anyone
    to type a password into a terminal."""
    base = get_settings().public_app_url.rstrip("/")
    if not base:
        raise SystemExit("Set PUBLIC_APP_URL first; the link needs the server's address")
    with SessionLocal() as db:
        user = _find(db, username)
        if user is None:
            raise SystemExit(f"No user {username!r}")
        token, expires = links.create(db, user)
        db.commit()
        print(f"{base}/welcome#{token}")
        print(f"Works once, until {expires:%Y-%m-%d %H:%M} UTC.")
    return 0


def _set_password(username: str, role: str | None, create: bool, from_stdin: bool) -> int:
    with SessionLocal() as db:
        user = _find(db, username)
        if user is None and not create:
            raise SystemExit(f"No user {username!r} (add --create to make one)")
        password = _read_password(from_stdin)
        problem = passwords.check_strength(password)
        if problem:
            raise SystemExit(f"The password needs {problem}")
        if user is None:
            user = User(username=username)
            set_role(user, role or "user")
            db.add(user)
        elif role:
            set_role(user, role)
        user.password_hash = passwords.hash_password(password)
        user.disabled = False
        db.flush()
        sessions.end_all(db, user.id)
        db.commit()
        print(f"{user.username}: password set, role {user.role}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kodex.core.auth.cli", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list the users")
    setter = commands.add_parser("set-password", help="set a user's password (and role)")
    setter.add_argument("username")
    setter.add_argument("--role", choices=ROLES)
    setter.add_argument("--create", action="store_true", help="create the user if there is none")
    setter.add_argument("--password-stdin", action="store_true")
    resetter = commands.add_parser("reset-two-factor", help="turn a user's two-step login off, remove their passkeys")
    resetter.add_argument("username")
    linker = commands.add_parser("sign-in-link", help="print a one-time link for a user to choose a password")
    linker.add_argument("username")
    args = parser.parse_args(argv)
    if args.command == "list":
        return _list()
    if args.command == "reset-two-factor":
        return _reset_two_factor(args.username)
    if args.command == "sign-in-link":
        return _sign_in_link(args.username)
    return _set_password(args.username, args.role, args.create, args.password_stdin)


if __name__ == "__main__":
    sys.exit(main())
