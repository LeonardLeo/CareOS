"""TOTP secrets, replay counters, and recovery codes (`08_Security_Architecture.md` Section 1).

`app_user.mfa_enrolled` has existed since the foundation migration and nothing ever set it —
a column describing an intention. These are the columns that make it a control.

`mfa_secret_encrypted` is a bytea like `dob_encrypted` and `tax_id_encrypted`, and encrypted
with the same key for the same reason: a second factor kept in plaintext is one a database
compromise hands over alongside the password hashes it exists to backstop.

`mfa_last_counter` is what makes a code single-use. Without it a code stays valid for its whole
thirty-second window no matter how many times it is presented, so one read over a shoulder is
one successful sign-in.

Revision ID: 0011_mfa_enforcement
Revises: 0010_account_disablement
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_mfa_enforcement"
down_revision: str | None = "0010_account_disablement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("mfa_secret_encrypted", sa.LargeBinary(), nullable=True))
    op.add_column("app_user", sa.Column("mfa_last_counter", sa.BigInteger(), nullable=True))
    op.add_column(
        "app_user",
        sa.Column(
            "mfa_recovery_hashes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            # Server default so the column can be NOT NULL on a table with existing rows.
            # An empty list is the truthful value for a user who has not enrolled: no codes,
            # rather than "unknown".
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    # DESTRUCTIVE-MIGRATION-APPROVED: reviewer=build-increment-19.
    #
    # Drops every enrolled user's TOTP secret and unused recovery codes. Downgrading past this
    # returns to code that neither reads nor enforces them, so the accounts still work — but
    # re-upgrading does not restore enrolment, and every affected user must enrol again. That
    # is the correct outcome rather than a regrettable one: a secret that survived a round trip
    # through a version that could not protect it should be replaced anyway.
    op.drop_column("app_user", "mfa_recovery_hashes")
    op.drop_column("app_user", "mfa_last_counter")
    op.drop_column("app_user", "mfa_secret_encrypted")
