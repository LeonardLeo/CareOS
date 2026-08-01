"""Reconciling delivered visits against their EVV records.

Every divergence here is a state the system currently reports as healthy. The transmission
worker retries failures and escalates exhaustion; none of these four is a failure. A visit
with no record at all has nothing to retry, a record parked in `transmitted` has already
succeeded as far as the worker is concerned, and a rejection is a finished job.

That is what makes these tests worth more than their line count: each one is a way for an
agency to deliver care it cannot bill for while every dashboard stays green.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from careos.core.crypto import encrypt_field
from careos.db.session import tenant_session
from careos.modules.compliance_rules import reconciliation
from careos.modules.credentialing.models import (
    Caregiver,
    EmploymentStatus,
    ExclusionCheckStatus,
)
from careos.modules.scheduling.models import (
    CaptureMethod,
    CarePlan,
    Client,
    ComplianceException,
    EVVRecord,
    ScheduledVisit,
    TransmissionStatus,
    VisitStatus,
)
from tests.conftest import TenantFixture

#: Comfortably past `DEFAULT_GRACE`, so nothing here is testing the boundary by accident.
LONG_AGO = timedelta(days=3)


async def _delivered_visit(
    tenant: TenantFixture,
    *,
    ended: timedelta = LONG_AGO,
    status: VisitStatus = VisitStatus.completed,
    transmission: TransmissionStatus | None = TransmissionStatus.acknowledged,
) -> uuid.UUID:
    """A visit that happened, optionally with an EVV record in a given state.

    `transmission=None` means no record at all — the case that has nothing to retry.
    """
    end = datetime.now(UTC) - ended
    async with tenant_session(tenant.agency_id) as session:
        care_client = Client(
            agency_id=tenant.agency_id,
            legal_name="Reconciled Client",
            dob_encrypted=encrypt_field("1938-02-02"),
            address_encrypted=encrypt_field("2 Somewhere St"),
            service_state="NY",
            primary_payer_type="medicaid_waiver",
        )
        session.add(care_client)
        await session.flush()

        plan = CarePlan(
            agency_id=tenant.agency_id,
            client_id=care_client.id,
            authorized_tasks=[],
            visit_frequency_rule={"rrule": "FREQ=DAILY;COUNT=1"},
            effective_start=(end - timedelta(days=1)).date(),
        )
        session.add(plan)
        await session.flush()

        caregiver = Caregiver(
            agency_id=tenant.agency_id,
            legal_name="Reconciled Aide",
            employment_status=EmploymentStatus.active,
            exclusion_check_status=ExclusionCheckStatus.cleared,
            exclusion_checked_at=datetime.now(UTC),
        )
        session.add(caregiver)
        await session.flush()

        visit = ScheduledVisit(
            agency_id=tenant.agency_id,
            care_plan_id=plan.id,
            caregiver_id=caregiver.id,
            scheduled_start=end - timedelta(hours=2),
            scheduled_end=end,
            status=status,
            service_state="NY",
            payer_type="medicaid_waiver",
        )
        session.add(visit)
        await session.flush()

        if transmission is not None:
            session.add(
                EVVRecord(
                    agency_id=tenant.agency_id,
                    scheduled_visit_id=visit.id,
                    clock_in_time=end - timedelta(hours=2),
                    clock_out_time=end,
                    capture_method=CaptureMethod.mobile_gps,
                    transmission_status=transmission,
                    aggregator_key="loopback",
                )
            )
            await session.flush()
        return visit.id


async def _run(tenant: TenantFixture) -> reconciliation.ReconciliationRun:
    async with tenant_session(tenant.agency_id) as session:
        return await reconciliation.reconcile(session, agency_id=tenant.agency_id)


async def _open_exceptions(tenant: TenantFixture) -> list[ComplianceException]:
    async with tenant_session(tenant.agency_id) as session:
        return list(
            (
                await session.execute(
                    select(ComplianceException).where(ComplianceException.resolved_at.is_(None))
                )
            )
            .scalars()
            .all()
        )


# --- The four divergences ------------------------------------------------------------------


async def test_a_delivered_visit_with_no_evv_record_is_reported(tenant_a: TenantFixture) -> None:
    """The one nothing else in the system can see.

    Retries, escalation, and the transmission-staleness alert are all keyed on an
    `evv_record`. When there is no row, every one of those mechanisms is looking at an empty
    set and reporting health.
    """
    visit_id = await _delivered_visit(tenant_a, transmission=None)
    run = await _run(tenant_a)

    assert [d.rule_key for d in run.divergences] == [reconciliation.RULE_NO_RECORD]
    assert run.divergences[0].visit_id == visit_id
    assert run.raised == 1


async def test_a_submitted_but_unacknowledged_visit_is_reported(tenant_a: TenantFixture) -> None:
    """`07_Integration_Specifications.md` Section 2: submitted is not compliant.

    The worker treats `transmitted` as a success and stops caring. From the outside it is an
    unbilled visit wearing a green light.
    """
    await _delivered_visit(tenant_a, transmission=TransmissionStatus.transmitted)
    run = await _run(tenant_a)
    assert [d.rule_key for d in run.divergences] == [reconciliation.RULE_UNACKNOWLEDGED]


async def test_a_record_still_queued_long_after_the_visit_is_reported(
    tenant_a: TenantFixture,
) -> None:
    """Pending three days after the visit ended means the worker never reached it."""
    await _delivered_visit(tenant_a, transmission=TransmissionStatus.pending)
    run = await _run(tenant_a)
    assert [d.rule_key for d in run.divergences] == [reconciliation.RULE_NEVER_SENT]


async def test_an_unresolved_rejection_is_reported(tenant_a: TenantFixture) -> None:
    """A rejection is a finished job to the worker and an unbillable visit to the agency."""
    await _delivered_visit(tenant_a, transmission=TransmissionStatus.rejected)
    run = await _run(tenant_a)
    assert [d.rule_key for d in run.divergences] == [reconciliation.RULE_REJECTED_UNRESOLVED]


# --- What must not be reported ---------------------------------------------------------------


async def test_an_acknowledged_visit_is_clean(tenant_a: TenantFixture) -> None:
    await _delivered_visit(tenant_a, transmission=TransmissionStatus.acknowledged)
    run = await _run(tenant_a)
    assert run.is_clean
    assert run.visits_examined == 1


async def test_a_cancelled_visit_owes_no_evv_record(tenant_a: TenantFixture) -> None:
    """No visit happened, so nothing is owed. Reporting it would be noise with a critical
    severity attached, which is the fastest way to make a queue unreadable."""
    await _delivered_visit(tenant_a, status=VisitStatus.cancelled, transmission=None)
    run = await _run(tenant_a)
    assert run.is_clean
    assert run.visits_examined == 0


async def test_a_visit_inside_the_grace_period_is_not_reported(tenant_a: TenantFixture) -> None:
    """The transmission worker backs off up to six hours.

    Anything tighter than the grace period would report the retry policy as a divergence,
    and a control that fires on the system working normally is one people turn off.
    """
    await _delivered_visit(
        tenant_a, ended=timedelta(hours=1), transmission=TransmissionStatus.pending
    )
    run = await _run(tenant_a)
    assert run.is_clean


async def test_a_visit_older_than_the_lookback_is_not_reported(tenant_a: TenantFixture) -> None:
    """A divergence from six months ago is a billing dispute, not an operational alert."""
    await _delivered_visit(tenant_a, ended=timedelta(days=200), transmission=None)
    run = await _run(tenant_a)
    assert run.is_clean


# --- The queue ------------------------------------------------------------------------------


async def test_running_twice_does_not_duplicate_the_exception(tenant_a: TenantFixture) -> None:
    """It runs daily. Duplicating on every pass would bury the queue within a week."""
    await _delivered_visit(tenant_a, transmission=None)
    await _run(tenant_a)
    second = await _run(tenant_a)

    assert second.raised == 0
    assert len(await _open_exceptions(tenant_a)) == 1


async def test_an_exception_closes_when_the_divergence_resolves(tenant_a: TenantFixture) -> None:
    """The half that decides whether anyone keeps reading the queue.

    A retransmission that succeeds tomorrow has to clear today's exception without a human
    dismissing it. Otherwise the queue fills with problems that are already fixed, and the
    real ones stop standing out.
    """
    visit_id = await _delivered_visit(tenant_a, transmission=TransmissionStatus.pending)
    await _run(tenant_a)
    assert len(await _open_exceptions(tenant_a)) == 1

    async with tenant_session(tenant_a.agency_id) as session:
        record = (
            (
                await session.execute(
                    select(EVVRecord).where(EVVRecord.scheduled_visit_id == visit_id)
                )
            )
            .scalars()
            .one()
        )
        record.transmission_status = TransmissionStatus.acknowledged

    run = await _run(tenant_a)
    assert run.is_clean
    assert run.resolved == 1
    assert await _open_exceptions(tenant_a) == []


async def test_a_changed_divergence_updates_rather_than_duplicating(
    tenant_a: TenantFixture,
) -> None:
    """Attempt counts move while the problem stays the same one."""
    visit_id = await _delivered_visit(tenant_a, transmission=TransmissionStatus.rejected)
    await _run(tenant_a)

    async with tenant_session(tenant_a.agency_id) as session:
        record = (
            (
                await session.execute(
                    select(EVVRecord).where(EVVRecord.scheduled_visit_id == visit_id)
                )
            )
            .scalars()
            .one()
        )
        record.transmission_attempts = 4

    await _run(tenant_a)
    open_now = await _open_exceptions(tenant_a)
    assert len(open_now) == 1
    assert open_now[0].details["transmission_attempts"] == 4


async def test_every_divergence_is_critical(tenant_a: TenantFixture) -> None:
    """Each one is a delivered visit that cannot be billed, and for a Medicaid client a
    compliance finding waiting to be made by somebody else."""
    await _delivered_visit(tenant_a, transmission=None)
    await _run(tenant_a)
    assert all(e.severity == "critical" for e in await _open_exceptions(tenant_a))


async def test_every_divergence_says_what_to_do_about_it(tenant_a: TenantFixture) -> None:
    """An exception queue that names problems without naming remedies is a worry list."""
    for transmission in (
        None,
        TransmissionStatus.transmitted,
        TransmissionStatus.pending,
        TransmissionStatus.rejected,
    ):
        await _delivered_visit(tenant_a, transmission=transmission)
    run = await _run(tenant_a)

    assert len(run.divergences) == 4
    for divergence in run.divergences:
        assert divergence.details.get("remediation"), f"{divergence.rule_key} has no remediation"


# --- Isolation and read-only paths -----------------------------------------------------------


async def test_reconciling_one_agency_does_not_see_another(
    tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    await _delivered_visit(tenant_b, transmission=None)
    run = await _run(tenant_a)
    assert run.visits_examined == 0
    assert run.is_clean


async def test_find_divergences_writes_nothing(tenant_a: TenantFixture) -> None:
    """So it can answer "are we actually compliant?" against production without side effects."""
    await _delivered_visit(tenant_a, transmission=None)
    async with tenant_session(tenant_a.agency_id) as session:
        divergences, examined = await reconciliation.find_divergences(session)
    assert len(divergences) == 1
    assert examined == 1
    assert await _open_exceptions(tenant_a) == []
