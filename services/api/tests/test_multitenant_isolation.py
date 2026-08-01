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


async def test_app_role_lacks_bypassrls(database: None) -> None:
    """The application role must not be able to bypass RLS or be a superuser."""
    async with tenant_session(None) as session:
        row = (
            await session.execute(
                text("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = 'careos_app'")
            )
        ).one()
    bypassrls, is_super = row
    assert not bypassrls, "careos_app holds BYPASSRLS — tenant isolation is defeated"
    assert not is_super, "careos_app is a superuser — superusers bypass RLS"


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
