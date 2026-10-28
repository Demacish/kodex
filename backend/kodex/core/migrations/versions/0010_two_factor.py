"""two-step login, passkeys and sign-in links

The OpenID Connect subject column gets a name that isn't v1's provider's;
two-step login (TOTP and recovery codes), passkeys, one-time sign-in links
and the challenges of unfinished logins get their tables (kodex.core.auth).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "authentik_sub", new_column_name="oidc_subject")
    op.execute("ALTER TABLE users RENAME CONSTRAINT users_authentik_sub_key TO users_oidc_subject_key")
    op.add_column("users", sa.Column("totp_secret", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("totp_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("webauthn_handle", sa.String(length=64), nullable=True))
    op.create_unique_constraint("users_webauthn_handle_key", "users", ["webauthn_handle"])
    op.add_column("oidc_logins", sa.Column("link_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "oidc_logins_link_user_id_fkey", "oidc_logins", "users", ["link_user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_table(
        "passkeys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False),
        sa.Column("transports", sa.JSON(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("backed_up", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="passkeys_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="passkeys_pkey"),
        sa.UniqueConstraint("credential_id", name="passkeys_credential_id_key"),
    )
    op.create_index("ix_passkeys_user_id", "passkeys", ["user_id"])
    op.create_table(
        "recovery_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="recovery_codes_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="recovery_codes_pkey"),
        sa.UniqueConstraint("code_hash", name="recovery_codes_code_hash_key"),
    )
    op.create_index("ix_recovery_codes_user_id", "recovery_codes", ["user_id"])
    op.create_table(
        "sign_in_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="sign_in_links_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="sign_in_links_pkey"),
        sa.UniqueConstraint("token_hash", name="sign_in_links_token_hash_key"),
    )
    op.create_index("ix_sign_in_links_user_id", "sign_in_links", ["user_id"])
    op.create_table(
        "auth_challenges",
        sa.Column("ticket", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("challenge", sa.LargeBinary(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="auth_challenges_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("ticket", name="auth_challenges_pkey"),
    )
    op.create_index("ix_auth_challenges_created_at", "auth_challenges", ["created_at"])


def downgrade() -> None:
    op.drop_table("auth_challenges")
    op.drop_table("sign_in_links")
    op.drop_table("recovery_codes")
    op.drop_table("passkeys")
    op.drop_constraint("oidc_logins_link_user_id_fkey", "oidc_logins", type_="foreignkey")
    op.drop_column("oidc_logins", "link_user_id")
    op.drop_constraint("users_webauthn_handle_key", "users", type_="unique")
    op.drop_column("users", "webauthn_handle")
    op.drop_column("users", "totp_last_step")
    op.drop_column("users", "totp_enabled_at")
    op.drop_column("users", "totp_secret")
    op.execute("ALTER TABLE users RENAME CONSTRAINT users_oidc_subject_key TO users_authentik_sub_key")
    op.alter_column("users", "oidc_subject", new_column_name="authentik_sub")
