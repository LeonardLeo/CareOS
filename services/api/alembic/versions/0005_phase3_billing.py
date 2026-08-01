"""Phase 3 tables: payer contracts, authorizations, claims, remittance.

Step 8 of `04_Data_Model_and_Schema.md` Section 8. Unused until Phase 3; present now so
that `scheduled_visit.authorization_id` has a real foreign key target and every visit
recorded from day one can be traced onto a claim line later without a backfill.

Revision ID: 0005_phase3_billing
Revises: 0004_phase2_documentation
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from careos.db.rls import standard_tenant_table

revision: str = "0005_phase3_billing"
down_revision: str | None = "0004_phase2_documentation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("payer_contract", "authorization", "claim", "claim_line", "remittance")


def _tenant_column() -> sa.Column:
    return sa.Column(
        "agency_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("agency.id", ondelete="RESTRICT"),
        nullable=False,
    )


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "payer_contract",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column("payer_name", sa.Text(), nullable=False),
        sa.Column("payer_type", sa.Text(), nullable=False),
        sa.Column("state_code", sa.Text(), nullable=True),
        sa.Column("edi_connection_config", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        *_timestamps(),
    )
    op.create_index("ix_payer_contract_agency_id", "payer_contract", ["agency_id"])

    op.create_table(
        "authorization",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "care_plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("care_plan.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payer_contract_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payer_contract.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("authorized_units", sa.Numeric(12, 2), nullable=False),
        sa.Column("units_used", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("auth_start", sa.Date(), nullable=False),
        sa.Column("auth_end", sa.Date(), nullable=True),
        sa.Column("authorization_number", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("units_used >= 0 AND authorized_units >= 0",
                           name="ck_authorization_units_non_negative"),
    )
    op.create_index("ix_authorization_agency_id", "authorization", ["agency_id"])
    op.create_index("ix_authorization_care_plan_id", "authorization", ["care_plan_id"])

    # Now that the target exists, close the loop on the forward-declared column added in
    # 0003. Until this point it was an unconstrained uuid by necessity.
    op.create_foreign_key(
        "fk_scheduled_visit_authorization",
        "scheduled_visit",
        "authorization",
        ["authorization_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "claim",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "payer_contract_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payer_contract.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("draft", "scrubbed", "submitted", "accepted", "rejected", "paid", "denied",
                    name="claim_status"),
            nullable=False,
        ),
        sa.Column("edi_837_payload", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.Date(), nullable=True),
        sa.Column("total_billed_amount", sa.Numeric(12, 2), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_claim_agency_id", "claim", ["agency_id"])

    op.create_table(
        "claim_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "claim_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("claim.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scheduled_visit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scheduled_visit.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "authorization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("authorization.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("billed_units", sa.Numeric(12, 2), nullable=False),
        sa.Column("billed_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("scrub_flags", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        *_timestamps(),
    )
    op.create_index("ix_claim_line_agency_id", "claim_line", ["agency_id"])
    op.create_index("ix_claim_line_claim_id", "claim_line", ["claim_id"])
    # A visit may legitimately be billed to more than one payer over time (a corrected
    # resubmission), but never twice on the same claim.
    op.create_index("uq_claim_line_claim_visit", "claim_line", ["claim_id", "scheduled_visit_id"],
                    unique=True)

    op.create_table(
        "remittance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "claim_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("claim.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("edi_835_payload", sa.Text(), nullable=True),
        sa.Column("paid_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("adjustment_reason_codes", postgresql.ARRAY(sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::text[]")),
        sa.Column("denial_category", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_remittance_agency_id", "remittance", ["agency_id"])
    op.create_index("ix_remittance_claim_id", "remittance", ["claim_id"])

    for table in _TABLES:
        for statement in standard_tenant_table(table):
            op.execute(statement)


def downgrade() -> None:
    op.drop_constraint("fk_scheduled_visit_authorization", "scheduled_visit", type_="foreignkey")
    for table in reversed(_TABLES):
        op.drop_table(table)
    op.execute("DROP TYPE IF EXISTS claim_status")
