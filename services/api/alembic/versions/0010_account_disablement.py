"""Why an account was disabled (`08_Security_Architecture.md` Section 6).

`user_status` already carried `suspended` and nothing ever set it, so disabling an account is
a behaviour change rather than a schema one. The single column added here is the reason, kept
beside the status because "why can this person not sign in?" is asked by whoever is looking at
the user list, and an answer that lives only in the audit log is one most people never get.

Nullable rather than defaulted: an account that has never been disabled has no reason, and a
placeholder string would make "disabled without a stated reason" indistinguishable from "never
disabled".

Revision ID: 0010_account_disablement
Revises: 0009_outbound_webhooks
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_account_disablement"
down_revision: str | None = "0009_outbound_webhooks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("disabled_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    # DESTRUCTIVE-MIGRATION-APPROVED: reviewer=build-increment-17.
    #
    # Drops the stated reason for every currently-disabled account. The disablement itself
    # survives — that is `app_user.status` — and every reason is also in the audit log, which
    # is append-only and not touched here. So this loses the convenient copy, not the record.
    op.drop_column("app_user", "disabled_reason")
