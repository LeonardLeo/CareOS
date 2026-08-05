"""Multi-tenant isolation tests.

`03_Technical_Architecture.md` Section 8 and `08_Security_Architecture.md` Section 2 both
require these to run in CI, and `12_Engineering_Handoff_Guide.md` Section 3 names them as
the tests most likely to have been skipped under time pressure and most costly to have
skipped. A cross-tenant leak is a Sev-1.

These deliberately attack the *database* layer, not just the API. Testing only through HTTP
would prove the handlers filter correctly, which is the weaker of the two guarantees. What
matters is that a handler which forgets to filter still cannot reach another tenant's rows.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from careos.db.models import RLS_TABLES
from careos.db.session import tenant_session
from careos.modules.agency.models import Role
from careos.modules.scheduling.models import Client
from tests.conftest import TenantFixture, make_client_with_plan


async def test_every_tenant_table_has_forced_rls(database: None) -> None:
    """Each tenant table must have RLS both enabled and FORCEd.

    `ENABLE` alone is insufficient: the table owner bypasses its own policies unless `FORCE`
    is set, which would make isolation depend on never connecting as the owner.
    """
    async with tenant_session(None) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relkind = 'r'
                    """
                )
            )
        ).all()

    by_table = {name: (enabled, forced) for name, enabled, forced in rows}
    for table in RLS_TABLES:
        assert table in by_table, f"{table} is missing from the database"
        enabled, forced = by_table[table]
        assert enabled, f"{table} does not have ROW LEVEL SECURITY enabled"
        assert forced, f"{table} does not have FORCE ROW LEVEL SECURITY"


@pytest.mark.parametrize(
    "role", ["careos_app", "careos_platform", "careos_platform_views"]
)
async def test_request_path_roles_lack_bypassrls(database: None, role: str) -> None:
    """None of the roles the application connects as may bypass RLS or be a superuser.

    `careos_app` was always here. `careos_platform` joined it when the CareOS operator
    console was built, and it is the one where the shortcut is most tempting: it legitimately
    needs to know something about every tenant, so "just give it BYPASSRLS" is the change
    somebody will eventually propose. The aggregate view exists so that is never necessary,
    and this is what stops it being done quietly anyway.

    `careos_platform_views` owns that view and therefore reads across tenants — but through
    explicit `TO careos_platform_views USING (true)` policies on nine named tables, not by
    bypassing the mechanism. The difference matters: a policy is greppable and a role
    attribute is not.

    `careos_auth` is deliberately absent from this list. It holds BYPASSRLS by design, for
    the two operations that precede knowing a tenant, and `test_privileged_role_is_narrow`
    below is what bounds it instead.
    """
    async with tenant_session(None) as session:
        row = (
            await session.execute(
                text("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = :role"),
                {"role": role},
            )
        ).one()
    bypassrls, is_super = row
    assert not bypassrls, f"{role} holds BYPASSRLS — tenant isolation is defeated"
    assert not is_super, f"{role} is a superuser — superusers bypass RLS"


async def test_the_view_owner_role_cannot_log_in(database: None) -> None:
    """`careos_platform_views` is an owner, not an account.

    It is the one role in the system with cross-tenant read policies on the tables that hold
    PHI. That is only acceptable while nothing can connect as it, so the whole design rests
    on this attribute.
    """
    async with tenant_session(None) as session:
        can_login = (
            await session.execute(
                text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'careos_platform_views'")
            )
        ).scalar_one()
    assert not can_login, (
        "careos_platform_views can log in — it owns the cross-tenant aggregate view, so a "
        "login for it is a login that reads every tenant's rows"
    )


async def test_platform_policies_did_not_widen_what_the_app_role_sees(
    tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    """Adding role-scoped policies must not change what `careos_app` is bound by.

    A PostgreSQL policy names the roles it applies to and is consulted only for a member of
    one of them, so the `TO careos_platform_views USING (true)` policies added in migration
    0013 should be invisible to `careos_app`. "Should be" is the reason this test exists: it
    is the exact assumption that, if wrong, turns the operator console into a cross-tenant
    leak reachable from every ordinary request.

    Asserted two ways — the policy inventory, and an actual cross-tenant read.
    """
    await make_client_with_plan(tenant_a)

    async with tenant_session(tenant_b.agency_id) as session:
        # Every policy on `client` that could apply to careos_app must still be the tenant
        # one. `polroles` is empty (meaning PUBLIC) for the tenant policy and names the view
        # owner for the aggregate one.
        rows = (
            await session.execute(
                text(
                    """
                    SELECT polname,
                           coalesce(
                               array_to_string(
                                   ARRAY(SELECT rolname FROM pg_roles
                                          WHERE oid = ANY(pol.polroles)), ','),
                               '')
                    FROM pg_policy pol
                    JOIN pg_class c ON c.oid = pol.polrelid
                    WHERE c.relname = 'client'
                    ORDER BY polname
                    """
                )
            )
        ).all()
        by_name = dict(rows)
        assert by_name["client_tenant_isolation"] == "", (
            "the tenant policy is no longer unconditional across roles"
        )
        assert by_name["client_platform_aggregate"] == "careos_platform_views", (
            "the aggregate policy is not restricted to the view-owner role"
        )

        # And the behaviour, not just the catalogue.
        assert (await session.execute(select(Client))).scalars().all() == []


#: Every relation a role holds any grant on, table-level or column-level.
#:
#: Read from `pg_class.relacl` and `pg_attribute.attacl` rather than from
#: `information_schema.role_table_grants`, which only reports grants involving the *current*
#: user. Connected as `careos_app`, the information-schema view returns an empty set for
#: every other role — so a test built on it passes vacuously, which is how the first version
#: of this reported that `careos_platform` could reach nothing at all.
_REACHABLE_RELATIONS_SQL = """
SELECT DISTINCT c.relname
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) acl
JOIN pg_roles r ON r.oid = acl.grantee
WHERE n.nspname = 'public' AND r.rolname = :role
UNION
SELECT DISTINCT c.relname
FROM pg_attribute att
JOIN pg_class c ON c.oid = att.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(att.attacl) acl
JOIN pg_roles r ON r.oid = acl.grantee
WHERE n.nspname = 'public' AND r.rolname = :role
"""


async def _reachable_relations(role: str) -> set[str]:
    async with tenant_session(None) as session:
        rows = (
            await session.execute(text(_REACHABLE_RELATIONS_SQL), {"role": role})
        ).scalars().all()
    return set(rows)


async def test_privileged_role_is_narrow(database: None) -> None:
    """`careos_auth` holds BYPASSRLS, so what it can reach at all is the boundary.

    Three tables — `agency`, `app_user`, `audit_log` — plus read-only reference data. A
    fourth appearing here means a pre-tenant code path grew a reach it should not have, and
    the whole argument for a separate pool rests on this staying short.
    """
    assert await _reachable_relations("careos_auth") == {
        "agency",
        "app_user",
        "audit_log",
        "credential_type_ref",
        "evv_aggregator_ref",
        "payer_service_code_ref",
    }


async def test_platform_role_reaches_no_tenant_table_but_agency(database: None) -> None:
    """The console's reach, asserted as an inventory rather than as a claim.

    This is the single most important assertion about the platform design. It is written as
    "here is the complete list" rather than "it cannot read `client`", because the failure
    mode being guarded against is a *new* grant added later for a good-sounding reason.
    """
    assert await _reachable_relations("careos_platform") == {
        # Column-scoped: six columns readable, four writable. Not `tax_id_encrypted`.
        "agency",
        # Write-only. The console records a suspension in the agency's own trail and cannot
        # read that trail back.
        "audit_log",
        # Counts and statuses, one row per agency.
        "platform_agency_health",
        # Its own two tables.
        "platform_audit_log",
        "platform_operator",
    }


async def test_cross_tenant_read_returns_nothing(
    tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    """Tenant B cannot read Tenant A's rows, even with an unfiltered query."""
    client_id, _plan_id = await make_client_with_plan(tenant_a)

    # Deliberately unfiltered: this is what a handler that forgot its WHERE clause does.
    async with tenant_session(tenant_b.agency_id) as session:
        visible = (await session.execute(select(Client))).scalars().all()
        assert visible == [], "Tenant B can see Tenant A's clients"

        by_id = await session.get(Client, client_id)
        assert by_id is None, "Tenant B fetched Tenant A's client by primary key"

    # And the row genuinely exists — otherwise this test would pass on an empty database.
    async with tenant_session(tenant_a.agency_id) as session:
        assert (await session.get(Client, client_id)) is not None


async def test_cross_tenant_update_affects_no_rows(
    tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    """An UPDATE issued under Tenant B cannot modify Tenant A's row."""
    client_id, _ = await make_client_with_plan(tenant_a)

    async with tenant_session(tenant_b.agency_id) as session:
        result = await session.execute(
            text("UPDATE client SET legal_name = 'HIJACKED' WHERE id = :cid"),
            {"cid": client_id},
        )
        assert result.rowcount == 0

    async with tenant_session(tenant_a.agency_id) as session:
        row = await session.get(Client, client_id)
        assert row is not None
        assert row.legal_name == "Test Client", "Tenant A's row was modified by Tenant B"


async def test_cross_tenant_delete_affects_no_rows(
    tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    client_id, _ = await make_client_with_plan(tenant_a)

    async with tenant_session(tenant_b.agency_id) as session:
        result = await session.execute(
            text("DELETE FROM client WHERE id = :cid"), {"cid": client_id}
        )
        assert result.rowcount == 0

    async with tenant_session(tenant_a.agency_id) as session:
        assert (await session.get(Client, client_id)) is not None


async def test_cannot_insert_row_belonging_to_another_tenant(
    tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    """The policy's WITH CHECK clause must block writing into another tenant.

    A USING-only policy would let Tenant B insert a row stamped with Tenant A's id — a row
    it could not then read, but which would corrupt Tenant A's data.
    """
    async with tenant_session(tenant_b.agency_id) as session:
        session.add(
            Client(
                agency_id=tenant_a.agency_id,
                legal_name="Smuggled",
                service_state="NY",
                primary_payer_type="private_pay",
            )
        )
        with pytest.raises(DBAPIError):
            await session.flush()


async def test_session_without_tenant_sees_nothing(tenant_a: TenantFixture) -> None:
    """An unset tenant GUC must fail closed.

    The policy compares against `nullif(current_setting(...), '')::uuid`, which is NULL when
    unset — and `agency_id = NULL` is never true. So forgetting to set the tenant yields no
    rows rather than every row.
    """
    await make_client_with_plan(tenant_a)

    async with tenant_session(None) as session:
        count = (await session.execute(select(func.count()).select_from(Client))).scalar_one()
        assert count == 0, "A session with no tenant context could read tenant data"


async def test_tenant_guc_does_not_leak_between_sessions(
    tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    """The tenant setting is transaction-local, so a pooled connection cannot carry it over."""
    await make_client_with_plan(tenant_a)

    async with tenant_session(tenant_a.agency_id) as session:
        assert (await session.execute(select(func.count()).select_from(Client))).scalar_one() == 1

    # Reusing the pool immediately afterwards with no tenant must see nothing.
    async with tenant_session(None) as session:
        assert (await session.execute(select(func.count()).select_from(Client))).scalar_one() == 0

    async with tenant_session(tenant_b.agency_id) as session:
        assert (await session.execute(select(func.count()).select_from(Client))).scalar_one() == 0


async def test_audit_log_is_append_only_for_the_app_role(tenant_a: TenantFixture) -> None:
    """The app role must hold no UPDATE or DELETE grant on `audit_log`.

    Immutability enforced by grants rather than by convention means a compromised
    application cannot rewrite the trail (`08_Security_Architecture.md` Section 4).
    """
    async with tenant_session(tenant_a.agency_id) as session:
        await session.execute(
            text(
                """
                INSERT INTO audit_log
                    (id, agency_id, action, entity_type, is_phi_access, occurred_at)
                VALUES (:id, :aid, 'test.action', 'test', false, now())
                """
            ),
            {"id": uuid.uuid4(), "aid": tenant_a.agency_id},
        )

    async with tenant_session(tenant_a.agency_id) as session:
        with pytest.raises(ProgrammingError):
            await session.execute(text("UPDATE audit_log SET action = 'tampered'"))

    async with tenant_session(tenant_a.agency_id) as session:
        with pytest.raises(ProgrammingError):
            await session.execute(text("DELETE FROM audit_log"))

    async with tenant_session(tenant_a.agency_id) as session:
        remaining = (
            await session.execute(text("SELECT count(*) FROM audit_log WHERE action='test.action'"))
        ).scalar_one()
        assert remaining == 1


async def test_api_rejects_path_naming_another_agency(
    client, tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    """A token for Tenant A cannot read Tenant B via a path parameter."""
    response = await client.get(
        f"/v1/agencies/{tenant_b.agency_id}", headers=tenant_a.headers(Role.owner_admin)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_api_list_is_scoped_to_the_token_tenant(
    client, tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    """Listing clients returns only the caller's tenant, with no filter supplied."""
    await make_client_with_plan(tenant_a)

    a_response = await client.get("/v1/clients", headers=tenant_a.headers())
    b_response = await client.get("/v1/clients", headers=tenant_b.headers())

    assert a_response.status_code == 200
    assert b_response.status_code == 200
    assert len(a_response.json()) == 1
    assert b_response.json() == []
