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
