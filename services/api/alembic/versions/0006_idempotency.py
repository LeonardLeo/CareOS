"""Idempotency records for externally-effecting mutations.

Revision ID: 0006_idempotency
Revises: 0005_phase3_billing
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from careos.db.rls import standard_tenant_table

revision: str = "0006_idempotency"
down_revision: str | None = "0005_phase3_billing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agency_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agency.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column(
            "state",
            sa.Enum("in_progress", "completed", name="idempotency_state"),
            nullable=False,
        ),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index("ix_idempotency_record_agency_id", "idempotency_record", ["agency_id"])
    op.create_index(
        "uq_idempotency_agency_endpoint_key",
        "idempotency_record",
        ["agency_id", "endpoint", "key"],
        unique=True,
    )

    for statement in standard_tenant_table("idempotency_record"):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("idempotency_record")
    op.execute("DROP TYPE IF EXISTS idempotency_state")
