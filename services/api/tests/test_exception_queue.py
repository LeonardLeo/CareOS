"""Compliance exception queue tests.

The table was write-only before this: the rules engine and EVV worker wrote findings and
nothing could read them back, which looks like coverage while providing none.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from careos.core.errors import ConflictError, NotFoundError
from careos.db.session import tenant_session
from careos.modules.agency.models import Role
from careos.modules.scheduling import exceptions_service
from careos.modules.scheduling.models import ComplianceException
from tests.conftest import TenantFixture


async def _add(tenant: TenantFixture, rule_key: str, severity: str, *, age_days: int = 0):
    async with tenant_session(tenant.agency_id) as session:
        row = ComplianceException(
            agency_id=tenant.agency_id,
            rule_key=rule_key,
            severity=severity,
            entity_type="visit",
            entity_id=tenant.agency_id,
            message=f"{rule_key} fired",
            details={},
        )
        session.add(row)
        await session.flush()
        if age_days:
            row.created_at = datetime.now(UTC) - timedelta(days=age_days)
            await session.flush()
        return row.id


async def test_queue_orders_by_severity_then_age(tenant_a: TenantFixture) -> None:
    """Most severe first; within a severity, oldest first.

    An exception that has sat unresolved for a week is a worse problem than one raised an
    hour ago, and a newest-first queue would bury exactly the ignored ones.
    """
    await _add(tenant_a, "b.recent_warning", "warning")
    await _add(tenant_a, "c.recent_critical", "critical")
    await _add(tenant_a, "a.old_critical", "critical", age_days=7)

    async with tenant_session(tenant_a.agency_id) as session:
        rows = await exceptions_service.list_exceptions(session)

    assert [r.rule_key for r in rows] == [
        "a.old_critical",
        "c.recent_critical",
        "b.recent_warning",
    ]


async def test_resolved_exceptions_are_excluded_by_default(tenant_a: TenantFixture) -> None:
    exception_id = await _add(tenant_a, "evv.missing_service_code", "warning")
    async with tenant_session(tenant_a.agency_id) as session:
        await exceptions_service.resolve_exception(
            session, principal=tenant_a.principal(), exception_id=exception_id, note="fixed"
        )
        open_rows = await exceptions_service.list_exceptions(session)
        all_rows = await exceptions_service.list_exceptions(session, include_resolved=True)

    assert open_rows == []
    assert len(all_rows) == 1


async def test_resolving_records_who_and_what(tenant_a: TenantFixture) -> None:
    """Resolution is an audited act by a named person, not a silent dismissal."""
    from sqlalchemy import select

    from careos.core.audit import AuditAction
    from careos.modules.audit.models import AuditLog

    exception_id = await _add(tenant_a, "evv.transmission_rejected", "critical")
    async with tenant_session(tenant_a.agency_id) as session:
        resolved = await exceptions_service.resolve_exception(
            session,
            principal=tenant_a.principal(),
            exception_id=exception_id,
            note="Resubmitted to the aggregator",
        )
        assert resolved.resolved_by_user_id == tenant_a.owner_id
        assert resolved.details["resolution_note"] == "Resubmitted to the aggregator"

        audits = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == AuditAction.compliance_exception_resolved.value
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(audits) == 1
    assert audits[0].actor_user_id == tenant_a.owner_id


async def test_resolving_twice_is_refused(tenant_a: TenantFixture) -> None:
    exception_id = await _add(tenant_a, "evv.outside_geofence", "warning")
    async with tenant_session(tenant_a.agency_id) as session:
        await exceptions_service.resolve_exception(
            session, principal=tenant_a.principal(), exception_id=exception_id, note=None
        )
        with pytest.raises(ConflictError):
            await exceptions_service.resolve_exception(
                session, principal=tenant_a.principal(), exception_id=exception_id, note=None
            )


async def test_resolving_an_unknown_exception_is_a_404(tenant_a: TenantFixture) -> None:
    import uuid

    async with tenant_session(tenant_a.agency_id) as session:
        with pytest.raises(NotFoundError):
            await exceptions_service.resolve_exception(
                session,
                principal=tenant_a.principal(),
                exception_id=uuid.uuid4(),
                note=None,
            )


async def test_summary_counts_by_severity(tenant_a: TenantFixture) -> None:
    await _add(tenant_a, "a.crit", "critical")
    await _add(tenant_a, "b.crit", "critical")
    await _add(tenant_a, "c.warn", "warning")

    async with tenant_session(tenant_a.agency_id) as session:
        summary = await exceptions_service.summarize(session)

    assert summary.total_open == 3
    assert summary.by_severity == {"critical": 2, "warning": 1}


async def test_queue_is_tenant_scoped(
    client, tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    await _add(tenant_a, "evv.missing_clock_time", "critical")

    a = await client.get("/v1/compliance-exceptions", headers=tenant_a.headers(Role.scheduler))
    b = await client.get("/v1/compliance-exceptions", headers=tenant_b.headers(Role.scheduler))

    assert len(a.json()) == 1
    assert b.json() == []


async def test_endpoints_are_reachable(client, tenant_a: TenantFixture) -> None:
    await _add(tenant_a, "evv.missing_service_code", "warning")

    listing = await client.get(
        "/v1/compliance-exceptions", headers=tenant_a.headers(Role.scheduler)
    )
    assert listing.status_code == 200
    exception_id = listing.json()[0]["id"]

    summary = await client.get(
        "/v1/compliance-exceptions/summary", headers=tenant_a.headers(Role.scheduler)
    )
    assert summary.status_code == 200
    assert summary.json()["total_open"] == 1

    resolved = await client.post(
        f"/v1/compliance-exceptions/{exception_id}/resolve",
        headers=tenant_a.headers(Role.scheduler),
        json={"note": "handled"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolved_at"] is not None


async def test_auditor_cannot_resolve(client, tenant_a: TenantFixture) -> None:
    """The auditor role is read-only tenant-wide."""
    exception_id = await _add(tenant_a, "evv.missing_clock_time", "critical")
    response = await client.post(
        f"/v1/compliance-exceptions/{exception_id}/resolve",
        headers=tenant_a.headers(Role.auditor),
        json={"note": "nope"},
    )
    assert response.status_code == 403
