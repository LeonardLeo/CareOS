"""Server-side session revocation.

`08_Security_Architecture.md` Section 6 requires an agency admin to be able to immediately cut
off access for a terminated caregiver, *including any offline-cached PHI on their device*. Until
now only the device half of that existed: the caregiver app clears its cached schedule when the
API rejects its token. Nothing could make the API reject it.

A single timestamp per user is enough, and is preferred here over a token denylist. A denylist
needs every issued `jti` retained until expiry and a store to check on each request; a watermark
compares the token's own `iat` against one column, invalidates every token issued before the
revocation in one write, and cannot grow unboundedly. The cost is that it revokes all of a
user's sessions rather than one device, which for this requirement is the desired behaviour
anyway — the point is to cut a person off, not a browser tab.

Revision ID: 0008_session_revocation
Revises: 0007_compliance_review_log
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_session_revocation"
down_revision: str | None = "0007_compliance_review_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("sessions_revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # DESTRUCTIVE-MIGRATION-APPROVED: reviewer=build-increment-8.
    #
    # Dropping this column loses the record of which users have had access cut off, which on a
    # downgrade would silently re-admit a terminated caregiver's outstanding tokens until they
    # expire (15 minutes). Assessed as acceptable only because the column is new in this
    # revision and a downgrade past it necessarily returns to code that does not check it.
    # A production rollback should force a re-login for affected users instead.
    op.drop_column("app_user", "sessions_revoked_at")
