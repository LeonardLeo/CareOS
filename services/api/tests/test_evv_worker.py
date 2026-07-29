"""EVV transmission worker tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from careos.db.session import tenant_session
from careos.modules.scheduling import service as scheduling
from careos.modules.scheduling.models import (
    CaptureMethod,
    CarePlan,
    ComplianceException,
    EVVRecord,
    ScheduledVisit,
    TransmissionStatus,
)
from careos.workers.evv_transmission import (
    BASE_BACKOFF,
    MAX_ATTEMPTS,
    MAX_BACKOFF,
    next_attempt_due,
    run_once,
)
from tests.conftest import TenantFixture, make_client_with_plan


def test_first_attempt_is_due_immediately() -> None:
    assert next_attempt_due(0, None) <= datetime.now(UTC)


def test_backoff_grows_exponentially() -> None:
    last = datetime(2026, 7, 29, 12, tzinfo=UTC)
    assert next_attempt_due(1, last) == last + BASE_BACKOFF
    assert next_attempt_due(2, last) == last + BASE_BACKOFF * 2
    assert next_attempt_due(3, last) == last + BASE_BACKOFF * 4


def test_backoff_is_capped() -> None:
    last = datetime(2026, 7, 29, 12, tzinfo=UTC)
    assert next_attempt_due(20, last) == last + MAX_BACKOFF


async def _completed_visit(tenant: TenantFixture) -> ScheduledVisit:
    """Produce one clocked-out visit ready for transmission."""
    _client_id, plan_id = await make_client_with_plan(tenant)
    now = datetime.now(UTC)
    async with tenant_session(tenant.agency_id) as session:
        plan = await session.get(CarePlan, plan_id)
        visits = await scheduling.generate_visits(
            session,
            principal=tenant.principal(),
            care_plan=plan,
            window=scheduling.GenerationWindow(
                start=now.date(), end=(now + timedelta(days=7)).date()
            ),
            duration_minutes=60,
        )
        visit = visits[0]
        from careos.modules.credentialing.models import Caregiver

        caregiver = await session.get(Caregiver, tenant.caregiver_id)
        await scheduling.assign_caregiver(
            session, principal=tenant.principal(), visit=visit, caregiver=caregiver
        )
        await scheduling.clock_in(
            session,
            principal=tenant.principal(),
            visit=visit,
            timestamp=now,
            capture_method=CaptureMethod.mobile_gps,
            lat=40.7128,
            lng=-74.0060,
        )
        await scheduling.clock_out(
            session,
            principal=tenant.principal(),
            visit=visit,
            timestamp=now + timedelta(hours=1),
            lat=40.7128,
            lng=-74.0060,
        )
        return visit


async def test_worker_transmits_pending_records(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    visit = await _completed_visit(tenant_a)

    run = await run_once(tenant_a.agency_id)
    assert run.attempted == 1
    assert run.acknowledged == 1

    async with tenant_session(tenant_a.agency_id) as session:
        record = (
            await session.execute(select(EVVRecord).where(EVVRecord.scheduled_visit_id == visit.id))
        ).scalar_one()
        assert record.transmission_status is TransmissionStatus.acknowledged
        assert record.six_element_snapshot is not None


async def test_worker_skips_already_acknowledged_records(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    """Re-running must not re-transmit — a duplicate at the aggregator is a real problem."""
    await _completed_visit(tenant_a)
    first = await run_once(tenant_a.agency_id)
    second = await run_once(tenant_a.agency_id)

    assert first.acknowledged == 1
    assert second.attempted == 0


async def test_worker_ignores_visits_without_a_clock_out(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    """An in-progress visit has no complete six-element set, so it is not yet transmissible."""
    _client_id, plan_id = await make_client_with_plan(tenant_a)
    now = datetime.now(UTC)
    async with tenant_session(tenant_a.agency_id) as session:
        from careos.modules.credentialing.models import Caregiver

        plan = await session.get(CarePlan, plan_id)
        visits = await scheduling.generate_visits(
            session,
            principal=tenant_a.principal(),
            care_plan=plan,
            window=scheduling.GenerationWindow(
                start=now.date(), end=(now + timedelta(days=7)).date()
            ),
            duration_minutes=60,
        )
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        await scheduling.assign_caregiver(
            session, principal=tenant_a.principal(), visit=visits[0], caregiver=caregiver
        )
        await scheduling.clock_in(
            session,
            principal=tenant_a.principal(),
            visit=visits[0],
            timestamp=now,
            capture_method=CaptureMethod.mobile_gps,
            lat=40.7128,
            lng=-74.0060,
        )

    run = await run_once(tenant_a.agency_id)
    assert run.attempted == 0


async def test_exhausted_retries_escalate_to_a_compliance_exception(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    """After MAX_ATTEMPTS the record stops retrying and a human is told."""
    visit = await _completed_visit(tenant_a)

    async with tenant_session(tenant_a.agency_id) as session:
        record = (
            await session.execute(select(EVVRecord).where(EVVRecord.scheduled_visit_id == visit.id))
        ).scalar_one()
        record.transmission_attempts = MAX_ATTEMPTS
        record.last_transmission_at = datetime.now(UTC)
        await session.flush()

    run = await run_once(tenant_a.agency_id)
    assert run.attempted == 0, "an exhausted record must not be retried"
    assert run.escalated == 1

    async with tenant_session(tenant_a.agency_id) as session:
        exception = (
            await session.execute(
                select(ComplianceException).where(
                    ComplianceException.rule_key == "evv.transmission_exhausted"
                )
            )
        ).scalar_one()
    assert exception.severity == "critical"
    assert exception.entity_id == visit.id


async def test_escalation_is_not_duplicated(tenant_a: TenantFixture, reference_data: None) -> None:
    visit = await _completed_visit(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        record = (
            await session.execute(select(EVVRecord).where(EVVRecord.scheduled_visit_id == visit.id))
        ).scalar_one()
        record.transmission_attempts = MAX_ATTEMPTS
        await session.flush()

    await run_once(tenant_a.agency_id)
    second = await run_once(tenant_a.agency_id)
    assert second.escalated == 0

    async with tenant_session(tenant_a.agency_id) as session:
        rows = (
            (
                await session.execute(
                    select(ComplianceException).where(
                        ComplianceException.rule_key == "evv.transmission_exhausted"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1


async def test_worker_is_tenant_scoped(
    tenant_a: TenantFixture, tenant_b: TenantFixture, reference_data: None
) -> None:
    """A run for one agency must not touch another's records."""
    await _completed_visit(tenant_a)

    run_b = await run_once(tenant_b.agency_id)
    assert run_b.attempted == 0

    run_a = await run_once(tenant_a.agency_id)
    assert run_a.attempted == 1
