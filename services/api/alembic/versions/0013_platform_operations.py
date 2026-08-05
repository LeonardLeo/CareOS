"""Platform operators, agency suspension, and the one cross-tenant aggregate view.

This is the schema half of the CareOS-global operator surface described in
`careos/modules/platform/models.py` and `08_Security_Architecture.md` Sections 1 and 2. It
is one revision rather than several because the pieces are only safe together: the operator
table without the grants is an identity with no reach, and the grants without the view are a
role with access to raw tenant rows.

**Nothing here weakens tenant isolation, and the reason is mechanical.** A PostgreSQL policy
names the roles it applies to, and the planner consults it only when `current_user` is a
member of one of them. Every policy added below names `careos_platform` or
`careos_platform_views`. `careos_app` — the role every tenant request runs as — is a member
of neither, so the only policy it is ever evaluated against remains the unconditional
`agency_id = nullif(current_setting('careos.agency_id', true), '')::uuid` it was already
bound by. `tests/test_multitenant_isolation.py` asserts that from a `careos_app` connection
after this migration has run, which is the check that would fail if the reasoning above were
wrong.

**What the platform role can reach, exhaustively:**

* `SELECT` on `platform_agency_health` — one row per agency, every column a status, an
  identifier the agency registered under, a `count(*)`, or a timestamp.
* `SELECT` on six named columns of `agency`, and `UPDATE` on three. Not `tax_id_encrypted`.
* `SELECT`/`INSERT`/`UPDATE` on `platform_operator` (its own accounts).
* `SELECT`/`INSERT` on `platform_audit_log` — append-only, like `audit_log`.
* `INSERT` on `audit_log`, with no `SELECT`. It can write into an agency's trail that the
  agency was suspended; it cannot read that trail.

It holds no grant of any kind on `client`, `caregiver`, `scheduled_visit`, `evv_record`,
`credential`, `applicant_profile`, `visit_note`, `claim`, or `app_user`. A platform handler
that tried to read one gets `permission denied for table client` from Postgres.

The aggregate view is owned by `careos_platform_views`, a `NOLOGIN` role that exists for no
other purpose. That indirection is what keeps `careos_platform` off the base tables: a view
resolves its base-table permissions and row-level security as its owner, so the owner is the
only thing that needs cross-tenant reach, and nothing can connect as it.

Requires `scripts/bootstrap_db.sql` to have been re-run, since it creates the two new roles.
Re-running it is safe and idempotent.

Revision ID: 0013_platform_operations
Revises: 0012_ranking_shadow_period
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from careos.db.rls import (
    PLATFORM_ROLE,
    PLATFORM_VIEW_OWNER_ROLE,
    allow_view_owner_to_aggregate,
    revoke_view_owner_aggregate,
)

revision: str = "0013_platform_operations"
down_revision: str | None = "0012_ranking_shadow_period"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Tables the aggregate view reads. The view owner gets SELECT and a `USING (true)` policy on
#: each; `careos_platform` gets neither. Listed once so the grant, the policy, and the
#: downgrade cannot drift apart.
_AGGREGATED_TABLES = (
    "agency",
    "app_user",
    "caregiver",
    "client",
    "scheduled_visit",
    "evv_record",
    "compliance_exception",
    "credential",
    "audit_log",
)

#: Columns of `agency` the platform role may read. Deliberately not `tax_id_encrypted`, not
#: `parent_org_id`, and not the ranking-shadow columns: none of the three are anything an
#: operator needs to answer "is this tenant healthy" or "should it be suspended", and a
#: column-level grant is the difference between that being a policy and being enforced.
_AGENCY_READABLE_COLUMNS = (
    "id",
    "legal_name",
    "status",
    "suspended_at",
    "suspended_reason",
    "created_at",
)

#: Columns the platform role may write. Suspension and nothing else — an operator cannot
#: rename an agency or change the states it operates in.
#:
#: `updated_at` is here because `TimestampMixin` declares `onupdate=func.now()`, so every ORM
#: update writes it. Leaving it out did not narrow anything useful: it made the suspension
#: fail with `permission denied for table agency`, and the two ways around that were to strip
#: the ORM's own bookkeeping out of the statement or to leave the row's modification time
#: wrong. A row whose `updated_at` does not move when it changes is worse than one an
#: operator can touch.
_AGENCY_WRITABLE_COLUMNS = ("status", "suspended_at", "suspended_reason", "updated_at")

#: One row per agency. Counts and statuses only; no name, address, date of birth, or
#: identifier of any client, caregiver, applicant, or user appears anywhere in it.
#:
#: Scalar subqueries rather than a chain of `LEFT JOIN ... GROUP BY`, because the counts are
#: over six unrelated tables with different filters and one grouped join per table would make
#: the row multiplication between them the reader's problem. Postgres plans each subquery
#: independently against the per-agency indexes those tables already carry.
_HEALTH_VIEW_SQL = """
CREATE VIEW platform_agency_health AS
SELECT
    a.id                                                     AS agency_id,
    a.legal_name                                             AS legal_name,
    a.status::text                                           AS status,
    a.suspended_at                                           AS suspended_at,
    a.suspended_reason                                       AS suspended_reason,
    a.service_states                                         AS service_states,
    a.service_lines                                          AS service_lines,
    a.created_at                                             AS created_at,

    (SELECT count(*) FROM app_user u
      WHERE u.agency_id = a.id)                              AS users_total,
    (SELECT count(*) FROM app_user u
      WHERE u.agency_id = a.id AND u.status = 'active')      AS users_active,
    (SELECT count(*) FROM app_user u
      WHERE u.agency_id = a.id AND u.status = 'active'
        AND u.role = 'owner_admin')                          AS owner_admins_active,
    -- Enrolment is a support signal, not a judgement: an agency whose privileged users have
    -- not enrolled is one whose people are about to be locked out of everything except the
    -- enrolment screen, and knowing that before they call is the point.
    (SELECT count(*) FROM app_user u
      WHERE u.agency_id = a.id AND u.status = 'active'
        AND u.mfa_enrolled = false
        AND u.role IN ('owner_admin', 'scheduler',
                       'clinical_supervisor', 'billing_rcm'))  AS users_missing_mfa,

    (SELECT count(*) FROM caregiver c
      WHERE c.agency_id = a.id
        AND c.employment_status = 'active')                  AS caregivers_active,
    (SELECT count(*) FROM client cl
      WHERE cl.agency_id = a.id AND cl.status = 'active')    AS clients_active,

    (SELECT count(*) FROM scheduled_visit v
      WHERE v.agency_id = a.id
        AND v.scheduled_start >= now()
        AND v.scheduled_start < now() + interval '7 days')   AS visits_next_7d,
    (SELECT count(*) FROM scheduled_visit v
      WHERE v.agency_id = a.id
        AND v.caregiver_id IS NULL
        AND v.scheduled_start >= now()
        AND v.scheduled_start < now() + interval '7 days')   AS visits_unfilled_next_7d,

    -- The four transmission states, separately. A single "unhealthy" number would hide the
    -- difference between a queue that has not drained yet and an aggregator rejecting
    -- everything, and those need different phone calls.
    (SELECT count(*) FROM evv_record e
      WHERE e.agency_id = a.id
        AND e.transmission_status = 'pending')               AS evv_pending,
    (SELECT count(*) FROM evv_record e
      WHERE e.agency_id = a.id
        AND e.transmission_status = 'transmitted')           AS evv_transmitted,
    (SELECT count(*) FROM evv_record e
      WHERE e.agency_id = a.id
        AND e.transmission_status = 'acknowledged')          AS evv_acknowledged,
    (SELECT count(*) FROM evv_record e
      WHERE e.agency_id = a.id
        AND e.transmission_status = 'rejected')              AS evv_rejected,
    -- Age is the signal a count cannot carry: ten pending records created this minute are a
    -- healthy queue, and one pending since Tuesday is a wedged worker.
    (SELECT min(e.created_at) FROM evv_record e
      WHERE e.agency_id = a.id
        AND e.transmission_status = 'pending')               AS evv_oldest_pending_at,

    (SELECT count(*) FROM compliance_exception x
      WHERE x.agency_id = a.id AND x.resolved_at IS NULL
        AND x.severity = 'critical')                         AS exceptions_open_critical,
    (SELECT count(*) FROM compliance_exception x
      WHERE x.agency_id = a.id AND x.resolved_at IS NULL
        AND x.severity = 'warning')                          AS exceptions_open_warning,
    (SELECT count(*) FROM compliance_exception x
      WHERE x.agency_id = a.id AND x.resolved_at IS NULL
        AND x.severity = 'info')                             AS exceptions_open_info,

    (SELECT count(*) FROM credential k
      WHERE k.agency_id = a.id
        AND k.expiration_date IS NOT NULL
        AND k.expiration_date < current_date)                AS credentials_expired,
    (SELECT count(*) FROM credential k
      WHERE k.agency_id = a.id
        AND k.expiration_date IS NOT NULL
        AND k.expiration_date >= current_date
        AND k.expiration_date < current_date + 30)           AS credentials_expiring_30d,

    -- "Is anyone actually using this tenant." One aggregate over one action name; the view
    -- owner can read `audit_log`, and `careos_platform` cannot, so no audit row is ever
    -- exposed — only the maximum of a timestamp column.
    (SELECT max(l.occurred_at) FROM audit_log l
      WHERE l.agency_id = a.id
        AND l.action = 'user.login_succeeded')               AS last_user_login_at
FROM agency a
"""


def _require_platform_roles() -> None:
    """Fail with an actionable message if the bootstrap script has not been re-run."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PLATFORM_ROLE}')
               OR NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = '{PLATFORM_VIEW_OWNER_ROLE}'
               ) THEN
                RAISE EXCEPTION
                    'Roles {PLATFORM_ROLE}/{PLATFORM_VIEW_OWNER_ROLE} are missing. Re-run '
                    'scripts/bootstrap_db.sql as a superuser (it is idempotent), or '
                    'provision them via Terraform in deployed environments.';
            END IF;
            -- Asserted here as well as in the bootstrap script, because a migration is the
            -- last point at which the schema and the roles are checked together, and a
            -- platform role holding BYPASSRLS would make every grant below meaningless.
            IF EXISTS (
                SELECT 1 FROM pg_roles
                WHERE rolname IN ('{PLATFORM_ROLE}', '{PLATFORM_VIEW_OWNER_ROLE}')
                  AND (rolbypassrls OR rolsuper)
            ) THEN
                RAISE EXCEPTION
                    'The platform roles must hold neither BYPASSRLS nor SUPERUSER.';
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _require_platform_roles()

    # --- Agency suspension --------------------------------------------------------------
    agency_status = sa.Enum("active", "suspended", name="agency_status")
    agency_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "agency",
        sa.Column(
            "status",
            postgresql.ENUM("active", "suspended", name="agency_status", create_type=False),
            nullable=False,
            # Server default so the column can be NOT NULL on a table with existing rows, and
            # so a tenant provisioned by a code path that has not heard of suspension is
            # active rather than null.
            server_default="active",
        ),
    )
    op.add_column("agency", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agency", sa.Column("suspended_reason", sa.Text(), nullable=True))

    # --- Platform identity --------------------------------------------------------------
    op.create_table(
        "platform_operator",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("platform_admin", "platform_support", name="platform_role"),
            nullable=False,
        ),
        sa.Column("auth_provider_id", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "suspended", name="platform_operator_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("mfa_enrolled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mfa_secret_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("mfa_last_counter", sa.BigInteger(), nullable=True),
        sa.Column(
            "mfa_recovery_hashes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("sessions_revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("email", name="uq_platform_operator_email"),
    )

    op.create_table(
        "platform_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "actor_operator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_operator.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column(
            "subject_agency_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agency.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "subject_operator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_operator.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("source_ip", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_platform_audit_log_actor_operator_id", "platform_audit_log", ["actor_operator_id"])
    op.create_index("ix_platform_audit_log_occurred", "platform_audit_log", ["occurred_at"])
    op.create_index(
        "ix_platform_audit_log_subject_agency",
        "platform_audit_log",
        ["subject_agency_id", "occurred_at"],
    )

    # Neither table is tenant-scoped, so neither carries RLS. They are declared in
    # `careos.db.models.GLOBAL_TABLES`, which is what stops the startup classification gate
    # treating the omission as an accident.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform_operator TO {PLATFORM_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON platform_audit_log TO {PLATFORM_ROLE}")
    # Append-only by grant, exactly as `audit_log` is. An operator console that could delete
    # its own access log is not an access log.
    op.execute(f"REVOKE UPDATE, DELETE ON platform_audit_log FROM {PLATFORM_ROLE}")

    # --- The one cross-tenant read ------------------------------------------------------
    for table in _AGGREGATED_TABLES:
        for statement in allow_view_owner_to_aggregate(table):
            op.execute(statement)

    op.execute(_HEALTH_VIEW_SQL)
    # Ownership is the mechanism, so it is set explicitly rather than inherited from whoever
    # ran the migration. A view is planned with its owner's permissions and its owner's
    # row-level security, which is precisely why `careos_platform` needs no grant on any base
    # table. In a deployed environment the migration role must be a member of this role for
    # the ALTER to be permitted; Terraform provisions it that way.
    op.execute(f"ALTER VIEW platform_agency_health OWNER TO {PLATFORM_VIEW_OWNER_ROLE}")
    op.execute(f"GRANT SELECT ON platform_agency_health TO {PLATFORM_ROLE}")

    # --- Suspension: the only tenant table the platform role may write ------------------
    #
    # Column-scoped on purpose. `GRANT UPDATE ON agency` would also let an operator rename an
    # agency or change the states it bills in, which is the agency's decision and not
    # CareOS's. Naming the columns makes the boundary a grant rather than a code review.
    op.execute(
        f"GRANT SELECT ({', '.join(_AGENCY_READABLE_COLUMNS)}) ON agency TO {PLATFORM_ROLE}"
    )
    op.execute(f"GRANT UPDATE ({', '.join(_AGENCY_WRITABLE_COLUMNS)}) ON agency TO {PLATFORM_ROLE}")
    op.execute(
        f"""
        CREATE POLICY agency_platform_operations ON agency
            FOR ALL
            TO {PLATFORM_ROLE}
            USING (true)
            WITH CHECK (true)
        """
    )

    # The platform role may write into an agency's own audit trail and may not read it.
    # Writing is what lets an agency see, in its own records, that CareOS suspended it and
    # why. Reading would be a cross-tenant disclosure of everything every agency has done.
    op.execute(f"GRANT INSERT ON audit_log TO {PLATFORM_ROLE}")
    op.execute(
        f"""
        CREATE POLICY audit_log_platform_insert ON audit_log
            FOR INSERT
            TO {PLATFORM_ROLE}
            WITH CHECK (true)
        """
    )


def downgrade() -> None:
    # DESTRUCTIVE-MIGRATION-APPROVED: reviewer=build-increment-21.
    #
    # Drops every platform operator account, their MFA secrets and recovery codes, and the
    # platform access log; and drops the suspension state from `agency`, which silently
    # reinstates any suspended tenant.
    #
    # Assessed as acceptable only because all of it is new in this revision: downgrading past
    # it returns to code that has no operator console and no concept of a suspended agency,
    # so there is nothing left able to read either. The consequence to state plainly is the
    # reinstatement — a tenant suspended for a security incident becomes live again the
    # moment this runs, so a downgrade against a database with a suspended agency needs that
    # agency disabled another way first (disabling its users) before the downgrade, not
    # after.
    op.execute(f"DROP POLICY IF EXISTS audit_log_platform_insert ON audit_log")
    op.execute(f"REVOKE INSERT ON audit_log FROM {PLATFORM_ROLE}")

    op.execute("DROP POLICY IF EXISTS agency_platform_operations ON agency")
    op.execute(
        f"REVOKE UPDATE ({', '.join(_AGENCY_WRITABLE_COLUMNS)}) ON agency FROM {PLATFORM_ROLE}"
    )
    op.execute(
        f"REVOKE SELECT ({', '.join(_AGENCY_READABLE_COLUMNS)}) ON agency FROM {PLATFORM_ROLE}"
    )

    op.execute("DROP VIEW IF EXISTS platform_agency_health")
    for table in _AGGREGATED_TABLES:
        for statement in revoke_view_owner_aggregate(table):
            op.execute(statement)

    op.execute(f"REVOKE ALL ON platform_audit_log FROM {PLATFORM_ROLE}")
    op.execute(f"REVOKE ALL ON platform_operator FROM {PLATFORM_ROLE}")
    op.drop_table("platform_audit_log")
    op.drop_table("platform_operator")
    sa.Enum(name="platform_operator_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="platform_role").drop(op.get_bind(), checkfirst=True)

    op.drop_column("agency", "suspended_reason")
    op.drop_column("agency", "suspended_at")
    op.drop_column("agency", "status")
    sa.Enum(name="agency_status").drop(op.get_bind(), checkfirst=True)
