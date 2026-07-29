"""Durable compliance review log.

`06_Compliance_and_Regulatory_Requirements.md` Section 9 sets a review cadence;
`12_Engineering_Handoff_Guide.md` Section 5 requires the outcome and date to be recorded
somewhere durable so a future team knows what was reviewed and when.

Revision ID: 0007_compliance_review_log
Revises: 0006_idempotency
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from careos.db.rls import standard_tenant_table

revision: str = "0007_compliance_review_log"
down_revision: str | None = "0006_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compliance_review",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agency_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agency.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "review_type",
            sa.Enum(
                "healthcare_counsel",
                "consent_law_state",
                "billing_coding_consultant",
                "ai_hiring_bias_audit",
                "cms_pps_rule_review",
                "evv_vendor_review",
                "new_state_entry",
                "security_penetration_test",
                name="compliance_review_type",
            ),
            nullable=False,
        ),
        sa.Column("performed_on", sa.Date(), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum(
                "passed",
                "passed_with_findings",
                "failed",
                "inconclusive",
                name="compliance_review_outcome",
            ),
            nullable=False,
        ),
        sa.Column("performed_by", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "recorded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("next_due_on", sa.Date(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_compliance_review_agency_id", "compliance_review", ["agency_id"])
    op.create_index(
        "ix_compliance_review_type_date",
        "compliance_review",
        ["agency_id", "review_type", "performed_on"],
    )

    for statement in standard_tenant_table("compliance_review"):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("compliance_review")
    op.execute("DROP TYPE IF EXISTS compliance_review_type")
    op.execute("DROP TYPE IF EXISTS compliance_review_outcome")
