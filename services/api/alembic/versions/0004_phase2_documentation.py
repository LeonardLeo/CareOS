"""Phase 2 tables: ambient session metadata and visit notes.

Step 7 of `04_Data_Model_and_Schema.md` Section 8. The tables ship now and stay unused
until Phase 2 work begins — see `careos/modules/documentation/models.py` for why.

Revision ID: 0004_phase2_documentation
Revises: 0003_scheduling_evv
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from careos.db.rls import standard_tenant_table

revision: str = "0004_phase2_documentation"
down_revision: str | None = "0003_scheduling_evv"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("ambient_session_metadata", "visit_note")


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
        "ambient_session_metadata",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "scheduled_visit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scheduled_visit.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("consent_captured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "consent_method",
            sa.Enum("verbal_logged", "written", name="consent_method"),
            nullable=True,
        ),
        sa.Column("consent_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("audio_retained", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("audio_s3_key", sa.Text(), nullable=True),
        sa.Column("transcript_s3_key", sa.Text(), nullable=True),
        *_timestamps(),
        # Consent is a legal precondition in two-party-consent states
        # (`06_Compliance...` Section 6), so the two invariants live in the database rather
        # than only in the service that happens to write the row today:
        #   - consent recorded as captured must say how it was captured and when;
        #   - audio may only be retained where consent was actually captured.
        sa.CheckConstraint(
            "(consent_captured IS FALSE) OR "
            "(consent_method IS NOT NULL AND consent_captured_at IS NOT NULL)",
            name="ck_ambient_consent_requires_method_and_time",
        ),
        sa.CheckConstraint(
            "(audio_retained IS FALSE) OR (consent_captured IS TRUE)",
            name="ck_ambient_audio_requires_consent",
        ),
    )
    op.create_index("ix_ambient_session_metadata_agency_id", "ambient_session_metadata",
                    ["agency_id"])
    op.create_index("ix_ambient_session_metadata_visit", "ambient_session_metadata",
                    ["scheduled_visit_id"])

    op.create_table(
        "visit_note",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "scheduled_visit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scheduled_visit.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "ambient_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ambient_session_metadata.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("structured_content", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("narrative_text", sa.Text(), nullable=True),
        sa.Column("caregiver_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supervisor_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "supervisor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("compliance_flags", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        *_timestamps(),
        # Human sign-off is unskippable (`09_UX...` principle 5): a supervisor cannot
        # co-sign a note the caregiver has not signed first.
        sa.CheckConstraint(
            "supervisor_reviewed_at IS NULL OR caregiver_signed_at IS NOT NULL",
            name="ck_visit_note_supervisor_after_caregiver",
        ),
    )
    op.create_index("ix_visit_note_agency_id", "visit_note", ["agency_id"])
    op.create_index("ix_visit_note_visit", "visit_note", ["scheduled_visit_id"])

    for table in _TABLES:
        for statement in standard_tenant_table(table):
            op.execute(statement)


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table)
    op.execute("DROP TYPE IF EXISTS consent_method")
