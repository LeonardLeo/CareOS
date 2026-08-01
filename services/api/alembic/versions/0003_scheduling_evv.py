"""Scheduling and EVV: clients, care plans, visits, EVV records, compliance exceptions.

Steps 3 and 4 of the migration sequence in `04_Data_Model_and_Schema.md` Section 8.

Revision ID: 0003_scheduling_evv
Revises: 0002_workforce
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from careos.db.rls import standard_tenant_table

revision: str = "0003_scheduling_evv"
down_revision: str | None = "0002_workforce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("client", "care_plan", "scheduled_visit", "evv_record", "compliance_exception")


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
        "client",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column("legal_name", sa.Text(), nullable=False),
        sa.Column("dob_encrypted", postgresql.BYTEA(), nullable=True),
        sa.Column("address_encrypted", postgresql.BYTEA(), nullable=True),
        sa.Column("geo_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("geo_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("service_state", sa.String(2), nullable=False),
        sa.Column("primary_payer_type", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "on_hold", "discharged", name="client_status"),
            nullable=False,
        ),
        *_timestamps(),
    )
    op.create_index("ix_client_agency_id", "client", ["agency_id"])

    op.create_table(
        "care_plan",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("client.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("authorized_tasks", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("visit_frequency_rule", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("effective_start", sa.Date(), nullable=False),
        sa.Column("effective_end", sa.Date(), nullable=True),
        sa.Column(
            "clinical_supervisor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("default_service_type_code", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_care_plan_agency_id", "care_plan", ["agency_id"])
    op.create_index("ix_care_plan_client_id", "care_plan", ["client_id"])

    op.create_table(
        "scheduled_visit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "care_plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("care_plan.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "caregiver_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("caregiver.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "assigned", "confirmed", "in_progress", "completed", "missed",
                    "cancelled", name="visit_status"),
            nullable=False,
        ),
        sa.Column("service_type_code", sa.Text(), nullable=True),
        sa.Column("service_state", sa.String(2), nullable=True),
        sa.Column("payer_type", sa.Text(), nullable=True),
        sa.Column("authorization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("required_tasks", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("client_local_uuid", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["service_type_code", "service_state", "payer_type"],
            ["payer_service_code_ref.code", "payer_service_code_ref.state_code",
             "payer_service_code_ref.payer_type"],
            name="fk_scheduled_visit_service_code",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("scheduled_end > scheduled_start",
                           name="ck_scheduled_visit_end_after_start"),
    )
    op.create_index("ix_scheduled_visit_agency_id", "scheduled_visit", ["agency_id"])
    op.create_index("ix_scheduled_visit_care_plan_id", "scheduled_visit", ["care_plan_id"])
    op.create_index("ix_scheduled_visit_agency_start", "scheduled_visit",
                    ["agency_id", "scheduled_start"])
    op.create_index("ix_scheduled_visit_caregiver_start", "scheduled_visit",
                    ["caregiver_id", "scheduled_start"])
    op.create_index("ix_scheduled_visit_client_local_uuid", "scheduled_visit",
                    ["client_local_uuid"])

    op.create_table(
        "evv_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "scheduled_visit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scheduled_visit.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("clock_in_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clock_out_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clock_in_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("clock_in_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("clock_out_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("clock_out_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column(
            "capture_method",
            sa.Enum("mobile_gps", "telephony", "manual_exception", name="capture_method"),
            nullable=False,
        ),
        sa.Column(
            "transmission_status",
            sa.Enum("pending", "transmitted", "acknowledged", "rejected",
                    name="transmission_status"),
            nullable=False,
        ),
        sa.Column("transmission_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_transmission_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aggregator_response_payload", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("aggregator_key", sa.Text(), nullable=True),
        sa.Column("six_element_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("client_local_uuid", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "clock_out_time IS NULL OR clock_in_time IS NULL OR clock_out_time >= clock_in_time",
            name="ck_evv_record_clock_order",
        ),
    )
    op.create_index("ix_evv_record_agency_id", "evv_record", ["agency_id"])
    op.create_index("ix_evv_record_client_local_uuid", "evv_record", ["client_local_uuid"])
    # Partial index over the retry queue: the transmission worker only ever scans rows that
    # have not reached a terminal state, and in steady state that is a small minority.
    op.create_index(
        "ix_evv_record_untransmitted",
        "evv_record",
        ["agency_id", "last_transmission_at"],
        postgresql_where=sa.text("transmission_status IN ('pending', 'transmitted')"),
    )

    op.create_table(
        "compliance_exception",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column("rule_key", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
    )
    op.create_index("ix_compliance_exception_agency_id", "compliance_exception", ["agency_id"])
    op.create_index("ix_compliance_exception_open", "compliance_exception",
                    ["agency_id", "resolved_at"])
    # One open exception per rule per entity. Re-running the rules engine on every clock-out
    # would otherwise pile up duplicates and bury the scheduler in noise.
    op.create_index(
        "uq_compliance_exception_open_rule_entity",
        "compliance_exception",
        ["agency_id", "rule_key", "entity_type", "entity_id"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )

    for table in _TABLES:
        for statement in standard_tenant_table(table):
            op.execute(statement)


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table)
    for enum_name in ("client_status", "visit_status", "capture_method", "transmission_status"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
