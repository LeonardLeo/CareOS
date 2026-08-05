"""SQL helpers for tenant isolation, shared by every migration.

Centralised so that enabling RLS on a new table is one call rather than four statements a
migration author might get subtly wrong. `08_Security_Architecture.md` Section 2 requires
RLS as an enforcement layer independent of the application; that only holds if it is
applied uniformly.

`FORCE ROW LEVEL SECURITY` is deliberate. Without it, the table owner bypasses its own
policies, which would mean isolation silently depends on never connecting as the owner.
With it, the policy applies to everyone except roles holding `BYPASSRLS` — which is only
the narrowly-scoped `careos_auth` role.
"""

from __future__ import annotations

from careos.db.session import TENANT_GUC

APP_ROLE = "careos_app"
PRIVILEGED_ROLE = "careos_auth"

#: The role the CareOS platform console connects as. **No `BYPASSRLS`, no superuser** —
#: asserted in `scripts/bootstrap_db.sql` and again in the isolation suite, because a
#: platform operator is the principal for whom the temptation to hand one over is strongest.
#:
#: Its cross-tenant reach is one `SELECT` grant on one aggregate view plus a column-scoped
#: grant on `agency`. It holds nothing on `client`, `caregiver`, `scheduled_visit`,
#: `evv_record`, `credential`, or `applicant_profile`, so a platform handler cannot read a
#: tenant row even by accident.
PLATFORM_ROLE = "careos_platform"

#: Owns the aggregate view, and cannot log in.
#:
#: The view is the only thing that reads across tenants, and something has to be allowed to.
#: The alternatives were to give `careos_platform` grants and policies on nine base tables —
#: which puts raw rows one forgotten `WHERE` away from a console handler — or to hand the
#: view to `careos_auth` and widen the role the login path uses. This is the third option:
#: a `NOLOGIN` role whose entire capability is to be the owner of a fixed set of views whose
#: SQL is fixed in a migration and projects nothing but counts and statuses. Nothing can
#: connect as it, so its grants are reachable only through those views.
#:
#: It has no `BYPASSRLS` either. Its reach is expressed as `FOR SELECT TO
#: careos_platform_views USING (true)` policies on the tables the view reads — additive
#: policies scoped to a role, so `careos_app` is unaffected and the tenant predicate it is
#: bound by keeps its single, unconditional form.
PLATFORM_VIEW_OWNER_ROLE = "careos_platform_views"

#: `nullif(..., '')` turns an unset or blank GUC into NULL, and `agency_id = NULL` matches
#: nothing. So the failure mode of forgetting to set the tenant is an empty result set,
#: never a cross-tenant read.
_TENANT_PREDICATE = f"agency_id = nullif(current_setting('{TENANT_GUC}', true), '')::uuid"


def _quote(table: str) -> str:
    """Quote a table identifier.

    Not optional: `authorization` — the table name given in
    `04_Data_Model_and_Schema.md` Section 5 — is a reserved word in Postgres, and unquoted
    DDL against it is a syntax error. Quoting everything keeps that from being a special
    case someone has to remember.
    """
    if '"' in table:
        raise ValueError(f"Refusing to quote suspicious table identifier: {table!r}")
    return f'"{table}"'


def enable_tenant_rls(table: str) -> list[str]:
    """Statements enabling forced RLS and the tenant policy on a tenant-scoped table."""
    quoted = _quote(table)
    return [
        f"ALTER TABLE {quoted} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {quoted} FORCE ROW LEVEL SECURITY",
        # USING governs which existing rows are visible; WITH CHECK governs which rows may
        # be written. Both are required — USING alone would let a handler insert a row
        # belonging to another tenant even though it could not read it back.
        f"""
        CREATE POLICY {_quote(f"{table}_tenant_isolation")} ON {quoted}
            FOR ALL
            USING ({_TENANT_PREDICATE})
            WITH CHECK ({_TENANT_PREDICATE})
        """,
    ]


def grant_app_crud(table: str) -> list[str]:
    return [f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_quote(table)} TO {APP_ROLE}"]


def grant_app_append_only(table: str) -> list[str]:
    """Grant SELECT and INSERT only — the mechanism behind an immutable audit trail.

    No UPDATE or DELETE grant means the application role cannot alter history even if the
    application itself is compromised (`08_Security_Architecture.md` Section 4).
    """
    quoted = _quote(table)
    return [
        f"GRANT SELECT, INSERT ON {quoted} TO {APP_ROLE}",
        f"REVOKE UPDATE, DELETE ON {quoted} FROM {APP_ROLE}",
    ]


def grant_app_read_only(table: str) -> list[str]:
    """For global reference tables: readable by the app, written only by migrations/seeds."""
    quoted = _quote(table)
    return [
        f"GRANT SELECT ON {quoted} TO {APP_ROLE}",
        f"GRANT SELECT ON {quoted} TO {PRIVILEGED_ROLE}",
    ]


def standard_tenant_table(table: str, *, append_only: bool = False) -> list[str]:
    """Full isolation setup for one tenant-scoped table."""
    statements = list(enable_tenant_rls(table))
    statements += grant_app_append_only(table) if append_only else grant_app_crud(table)
    return statements


def allow_view_owner_to_aggregate(table: str) -> list[str]:
    """Let the view-owner role read `table` across tenants, and nothing else read it that way.

    Two statements, and both are needed for different reasons. The `GRANT` satisfies the
    ordinary permission check; the policy satisfies row-level security, which `FORCE ROW
    LEVEL SECURITY` applies even to the table's owner.

    `TO {PLATFORM_VIEW_OWNER_ROLE}` is what keeps this from being a hole. A policy names the
    roles it applies to, and Postgres consults it only when `current_user` is a member of
    one of them. `careos_app` is not, so the tenant policy remains the only policy it is ever
    evaluated against — the isolation suite asserts exactly that, from a `careos_app`
    connection, after this exists.

    `FOR SELECT` rather than `FOR ALL`: the view is read-only, and a role that cannot log in
    still should not carry a write path nobody intends to use.
    """
    quoted = _quote(table)
    return [
        f"GRANT SELECT ON {quoted} TO {PLATFORM_VIEW_OWNER_ROLE}",
        f"""
        CREATE POLICY {_quote(f"{table}_platform_aggregate")} ON {quoted}
            FOR SELECT
            TO {PLATFORM_VIEW_OWNER_ROLE}
            USING (true)
        """,
    ]


def revoke_view_owner_aggregate(table: str) -> list[str]:
    """Undo :func:`allow_view_owner_to_aggregate`, for a migration downgrade."""
    quoted = _quote(table)
    return [
        f'DROP POLICY IF EXISTS {_quote(f"{table}_platform_aggregate")} ON {quoted}',
        f"REVOKE SELECT ON {quoted} FROM {PLATFORM_VIEW_OWNER_ROLE}",
    ]
