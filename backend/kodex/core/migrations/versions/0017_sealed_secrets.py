"""room for sealed authenticator secrets (kodex.core.sealed): a Fernet
token is longer than the 64 characters a plain secret needed

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "totp_secret", type_=sa.String(length=255), existing_type=sa.String(length=64),
                    existing_nullable=True)  # fmt: skip


def downgrade() -> None:
    # A sealed secret doesn't fit back; downgrading turns two-step login off for those users.
    op.execute("UPDATE users SET totp_secret = NULL, totp_enabled_at = NULL WHERE length(totp_secret) > 64")
    op.alter_column("users", "totp_secret", type_=sa.String(length=64), existing_type=sa.String(length=255),
                    existing_nullable=True)  # fmt: skip
