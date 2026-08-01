"""Workforce: applicants, caregivers, credentials, screening.

Steps 2 of the migration sequence in `04_Data_Model_and_Schema.md` Section 8.

Revision ID: 0002_workforce
Revises: 0001_foundation
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from careos.db.rls import standard_tenant_table

revision: str = "0002_workforce"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("job_posting", "applicant_profile", "caregiver", "credential", "screening_request")


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
        "job_posting",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("required_credential_types", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("service_state", sa.Text(), nullable=True),
        sa.Column("syndication_status", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        *_timestamps(),
    )
    op.create_index("ix_job_posting_agency_id", "job_posting", ["agency_id"])

    op.create_table(
        "applicant_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "job_posting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_posting.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.Text(), nullable=False, server_default="direct"),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("claimed_credentials", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("availability", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("resume_s3_key", sa.Text(), nullable=True),
        sa.Column("geo_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("geo_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("ranking_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("ranking_factors", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("ranked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ranking_model_version", sa.Text(), nullable=True),
        sa.Column(
            "pipeline_stage",
            sa.Enum("applied", "screened", "offer", "hired", "rejected", name="pipeline_stage"),
            nullable=False,
        ),
        sa.Column("stage_changed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        # US-1.2.2 requires every AI score to carry its explanatory factors, and the fair
        # hiring posture in `06_Compliance...` Section 5 depends on that record existing.
        # Enforced in the database so a code path cannot write a bare, unexplainable score.
        sa.CheckConstraint(
            "ranking_score IS NULL OR jsonb_array_length(ranking_factors) > 0",
            name="ck_applicant_ranking_score_requires_factors",
        ),
    )
    op.create_index("ix_applicant_profile_agency_id", "applicant_profile", ["agency_id"])

    op.create_table(
        "caregiver",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "app_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "applicant_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applicant_profile.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("legal_name", sa.Text(), nullable=False),
        sa.Column("dob_encrypted", postgresql.BYTEA(), nullable=True),
        sa.Column("address_encrypted", postgresql.BYTEA(), nullable=True),
        sa.Column(
            "employment_status",
            sa.Enum("applicant", "onboarding", "active", "inactive", "terminated",
                    name="employment_status"),
            nullable=False,
        ),
        sa.Column(
            "exclusion_check_status",
            sa.Enum("not_run", "cleared", "flagged", name="exclusion_check_status"),
            nullable=False,
        ),
        sa.Column("exclusion_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("geo_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("geo_lng", sa.Numeric(9, 6), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_caregiver_agency_id", "caregiver", ["agency_id"])

    op.create_table(
        "credential",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "caregiver_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("caregiver.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "credential_type",
            sa.Text(),
            sa.ForeignKey("credential_type_ref.code", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("issuing_body", sa.Text(), nullable=True),
        sa.Column("credential_number", sa.Text(), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("expiration_date", sa.Date(), nullable=True),
        sa.Column(
            "verification_status",
            sa.Enum("pending", "verified", "expired", "rejected", name="verification_status"),
            nullable=False,
        ),
        sa.Column("document_s3_key", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_credential_agency_id", "credential", ["agency_id"])
    op.create_index("ix_credential_caregiver_id", "credential", ["caregiver_id"])
    op.create_index("ix_credential_expiration_date", "credential", ["expiration_date"])

    op.create_table(
        "screening_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "caregiver_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("caregiver.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vendor_key", sa.Text(), nullable=False),
        sa.Column("check_types", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("vendor_request_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="initiated"),
        sa.Column("result_payload", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_screening_request_agency_id", "screening_request", ["agency_id"])
    op.create_index("ix_screening_request_caregiver_id", "screening_request", ["caregiver_id"])
    op.create_index("ix_screening_request_vendor_request_id", "screening_request",
                    ["vendor_request_id"])

    for table in _TABLES:
        for statement in standard_tenant_table(table):
            op.execute(statement)


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table)
    for enum_name in ("pipeline_stage", "employment_status", "exclusion_check_status",
                      "verification_status"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
