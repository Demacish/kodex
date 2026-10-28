"""Roles: ``admin`` (everything), ``user`` (reads, follows, requests),
``guest`` (reads only: no requests). ``User.is_admin``, which v1's routes
check, follows the role; app.auth.require_member refuses guests."""

from __future__ import annotations

from app.models.user import User

ROLES = ("admin", "user", "guest")


def set_role(user: User, role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"Unknown role {role!r}")
    user.role = role
    user.is_admin = role == "admin"


def apply_admin_group(user: User, in_admin_group: bool) -> bool:
    """With an admin group at the identity provider, membership decides
    whether the user is an admin; returns whether anything changed."""
    if in_admin_group and user.role != "admin":
        set_role(user, "admin")
        return True
    if not in_admin_group and user.role == "admin":
        set_role(user, "user")
        return True
    return False
