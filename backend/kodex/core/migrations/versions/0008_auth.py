"""auth

The backend owns authentication (ADR 0007): users get a role (admin for
v1's admins, user for the rest), an optional argon2id password and a
disabled flag, and authentik_sub becomes optional (a local account has
none). New tables: user_sessions (web sessions, hashed), api_keys (personal
keys for apps, OPDS, KOSync and Kobo, hashed), login_failures and
oidc_logins (OpenID Connect logins in progress).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "authentik_sub", existing_type=sa.String(length=255), nullable=True)
    op.add_column("users", sa.Column("role", sa.String(length=16), server_default="user", nullable=False))
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("disabled", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.execute("UPDATE users SET role = 'admin' WHERE is_admin")
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="user_sessions_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="user_sessions_pkey"),
        sa.UniqueConstraint("token_hash", name="user_sessions_token_hash_key"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("md5", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="api_keys_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="api_keys_pkey"),
        sa.UniqueConstraint("key_hash", name="api_keys_key_hash_key"),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_md5", "api_keys", ["md5"])
    op.create_table(
        "login_failures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="login_failures_pkey"),
    )
    op.create_index("ix_login_failures_username", "login_failures", ["username"])
    op.create_index("ix_login_failures_ip", "login_failures", ["ip"])
    op.create_index("ix_login_failures_at", "login_failures", ["at"])
    op.create_table(
        "oidc_logins",
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("next_path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("state", name="oidc_logins_pkey"),
    )


def downgrade() -> None:
    op.drop_table("oidc_logins")
    op.drop_table("login_failures")
    op.drop_table("api_keys")
    op.drop_table("user_sessions")
    op.drop_column("users", "disabled")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "role")
    op.alter_column("users", "authentik_sub", existing_type=sa.String(length=255), nullable=False)
