"""Foundation: tenants, users, global reference tables, audit log.

Step 1, 5 and 6 of the migration sequence in `04_Data_Model_and_Schema.md` Section 8.
The audit log lands here, before any other table carries production data, because that
document is explicit that it "should never be 'added later'".

Revision ID: 0001_foundation
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from careos.db.rls import APP_ROLE, PRIVILEGED_ROLE, grant_app_read_only, standard_tenant_table

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _require_roles() -> None:
    """Fail with an actionable message if the bootstrap script has not been run."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}')
               OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PRIVILEGED_ROLE}') THEN
                RAISE EXCEPTION
                    'Roles {APP_ROLE}/{PRIVILEGED_ROLE} are missing. Run scripts/bootstrap_db.sql '
                    'as a superuser first (or provision them via Terraform in deployed envs).';
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _require_roles()

    op.create_table(
        "agency",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("legal_name", sa.Text(), nullable=False),
        sa.Column("tax_id_encrypted", postgresql.BYTEA(), nullable=True),
        sa.Column("service_states", postgresql.ARRAY(sa.String(2)), nullable=False),
        sa.Column("service_lines", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("accepted_payer_types", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "parent_org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agency.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )

    op.create_table(
        "app_user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agency_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agency.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.Enum(
                "owner_admin", "scheduler", "clinical_supervisor", "caregiver", "billing_rcm",
                "auditor", name="user_role",
            ),
            nullable=False,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("auth_provider_id", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("invited", "active", "suspended", name="user_status"),
            nullable=False,
        ),
        sa.Column("mfa_enrolled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.UniqueConstraint("email", name="uq_app_user_email"),
    )
    op.create_index("ix_app_user_agency_id", "app_user", ["agency_id"])

    # --- Global reference tables (no agency_id, no RLS) -------------------------------
    op.create_table(
        "credential_type_ref",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("state_requirements", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("blocks_scheduling_on_expiry", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )

    op.create_table(
        "evv_aggregator_ref",
        sa.Column("state_code", sa.String(2), primary_key=True),
        sa.Column("adapter_key", sa.Text(), nullable=False),
        sa.Column(
            "evv_model",
            sa.Enum(
                "state_mandated_vendor", "state_provided_open_system",
                "open_vendor_to_aggregator", name="evv_model",
            ),
            nullable=False,
        ),
        sa.Column("aggregator_name", sa.Text(), nullable=False),
        sa.Column("connection_config", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("sandbox_validated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )

    op.create_table(
        "payer_service_code_ref",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("state_code", sa.String(2), primary_key=True),
        sa.Column("payer_type", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("unit_minutes", sa.Integer(), nullable=True),
        sa.Column("billing_rules", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("requires_evv", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )

    # --- Audit log --------------------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agency_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agency.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("after_state", postgresql.JSONB(), nullable=True),
        sa.Column("is_phi_access", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("source_ip", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index("ix_audit_log_agency_id", "audit_log", ["agency_id"])
    op.create_index("ix_audit_log_entity", "audit_log", ["agency_id", "entity_type", "entity_id"])
    op.create_index("ix_audit_log_occurred", "audit_log", ["agency_id", "occurred_at"])

    # --- Isolation and grants ----------------------------------------------------------
    # `agency` is the tenant root, so its policy compares `id`, not `agency_id`, and INSERT
    # must stay open: provisioning a new tenant happens before that tenant exists. The
    # insert path is reachable only through the separately-credentialed privileged pool.
    op.execute("ALTER TABLE agency ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agency FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY agency_tenant_isolation ON agency
            FOR ALL
            USING (id = nullif(current_setting('careos.agency_id', true), '')::uuid)
            WITH CHECK (id = nullif(current_setting('careos.agency_id', true), '')::uuid)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON agency TO {APP_ROLE}")

    for statement in standard_tenant_table("app_user"):
        op.execute(statement)
    for statement in standard_tenant_table("audit_log", append_only=True):
        op.execute(statement)
    for table in ("credential_type_ref", "evv_aggregator_ref", "payer_service_code_ref"):
        for statement in grant_app_read_only(table):
            op.execute(statement)

    # The privileged role touches only the tables the pre-tenant paths need: `agency` and
    # `app_user` for provisioning and login, plus `audit_log` — because agency creation and
    # login attempts are themselves auditable events, and they occur before any tenant
    # context exists. It is append-only here too: no UPDATE or DELETE on the audit trail for
    # any application role.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON agency TO {PRIVILEGED_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON app_user TO {PRIVILEGED_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON audit_log TO {PRIVILEGED_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON audit_log FROM {PRIVILEGED_ROLE}")


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("payer_service_code_ref")
    op.drop_table("evv_aggregator_ref")
    op.drop_table("credential_type_ref")
    op.drop_table("app_user")
    op.drop_table("agency")
    for enum_name in ("user_role", "user_status", "evv_model"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
