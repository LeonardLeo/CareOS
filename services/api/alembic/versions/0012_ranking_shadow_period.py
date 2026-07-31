"""The flag that makes a ranking shadow period possible (`13_Phase_1_Launch_Plan.md` 6.3).

`06_Compliance_and_Regulatory_Requirements.md` Section 5 requires a bias audit before the
ranking model influences hiring. The audit needs outcomes; outcomes need the model to have
influenced hiring. The way out of that circle is to run the scorer and withhold its output
from the people making decisions, which produces real outcomes carrying no adverse-impact
exposure — nothing the model said reached a decision-maker.

Defaults to false, so an agency provisioned tomorrow is in the shadow period without anyone
remembering to put it there. Turning it on is the deliberate act, and it is the one that
should require a dated audit behind it.

Per-agency rather than global: agencies join at different times, and the first cohort of one
is not evidence about another's workforce.

Revision ID: 0012_ranking_shadow_period
Revises: 0011_mfa_enforcement
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_ranking_shadow_period"
down_revision: str | None = "0011_mfa_enforcement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agency",
        sa.Column(
            "ranking_display_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Set when the flag was turned on, and by which audit. Nullable because the answer for an
    # agency still in the shadow period is genuinely "never", and because a boolean with no
    # date behind it cannot evidence that an audit preceded it.
    op.add_column(
        "agency",
        sa.Column("ranking_display_enabled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agency", "ranking_display_enabled_at")
    op.drop_column("agency", "ranking_display_enabled")
