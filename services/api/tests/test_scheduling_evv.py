"""Scheduling, compliance gates, and the EVV golden path.

Covers the flow in `03_Technical_Architecture.md` Section 6: care plan → generated visits →
assignment → clock-in → clock-out → EVV transmission, with the hard gates from PRD US-1.3.2
and US-1.4.3 asserted along the way.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from careos.core.errors import ComplianceGateError, ConflictError
from careos.db.session import tenant_session
from careos.integrations.evv.adapters.loopback import LoopbackAdapter
from careos.integrations.evv.base import EVVElementError, EVVPayload, TransmissionOutcome
from careos.integrations.evv.registry import resolve_for_state
from careos.modules.credentialing.models import (
    Caregiver,
    Credential,
    EmploymentStatus,
    ExclusionCheckStatus,
    VerificationStatus,
)
from careos.modules.scheduling import service as scheduling
from careos.modules.scheduling.models import (
    CaptureMethod,
    CarePlan,
    EVVRecord,
    ScheduledVisit,
    TransmissionStatus,
    VisitStatus,
)
from tests.conftest import TenantFixture, make_client_with_plan


async def _seed_visit(tenant: TenantFixture, **plan_kwargs) -> uuid.UUID:
    """Generate one visit for the tenant and return its id."""
    _client_id, plan_id = await make_client_with_plan(tenant, **plan_kwargs)
    async with tenant_session(tenant.agency_id) as session:
        plan = await session.get(CarePlan, plan_id)
        assert plan is not None
        visits = await scheduling.generate_visits(
            session,
            principal=tenant.principal(),
            care_plan=plan,
            window=scheduling.GenerationWindow(
                start=datetime.now(UTC).date(),
                end=(datetime.now(UTC) + timedelta(days=7)).date(),
            ),
            duration_minutes=60,
        )
        assert visits
        return visits[0].id


# --- Visit generation ------------------------------------------------------------------


async def test_generate_visits_materializes_from_the_rrule(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    _client_id, plan_id = await make_client_with_plan(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        plan = await session.get(CarePlan, plan_id)
        visits = await scheduling.generate_visits(
            session,
            principal=tenant_a.principal(),
            care_plan=plan,
            window=scheduling.GenerationWindow(
                start=datetime.now(UTC).date(),
                end=(datetime.now(UTC) + timedelta(days=7)).date(),
            ),
            duration_minutes=90,
        )

    assert len(visits) == 3  # FREQ=DAILY;COUNT=3
    first = visits[0]
    assert first.status is VisitStatus.open
    assert (first.scheduled_end - first.scheduled_start) == timedelta(minutes=90)
    # Billing-relevant fields are populated in Phase 1 even though nothing reads them yet.
    assert first.service_type_code == "T1019"
    assert first.service_state == "NY"
    assert first.payer_type == "medicaid_waiver"
    assert first.required_tasks == [{"code": "bathing", "label": "Assist with bathing"}]


async def test_regenerating_the_same_window_does_not_duplicate(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    _client_id, plan_id = await make_client_with_plan(tenant_a)
    window = scheduling.GenerationWindow(
        start=datetime.now(UTC).date(), end=(datetime.now(UTC) + timedelta(days=7)).date()
    )
    async with tenant_session(tenant_a.agency_id) as session:
        plan = await session.get(CarePlan, plan_id)
        first = await scheduling.generate_visits(
            session,
            principal=tenant_a.principal(),
            care_plan=plan,
            window=window,
            duration_minutes=60,
        )
        second = await scheduling.generate_visits(
            session,
            principal=tenant_a.principal(),
            care_plan=plan,
            window=window,
            duration_minutes=60,
        )
    assert len(first) == 3
    assert second == []


async def test_invalid_rrule_is_rejected(tenant_a: TenantFixture, reference_data: None) -> None:
    _client_id, plan_id = await make_client_with_plan(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        plan = await session.get(CarePlan, plan_id)
        plan.visit_frequency_rule = {"rrule": "NOT-AN-RRULE"}
        await session.flush()
        with pytest.raises(ConflictError):
            await scheduling.generate_visits(
                session,
                principal=tenant_a.principal(),
                care_plan=plan,
                window=scheduling.GenerationWindow(
                    start=datetime.now(UTC).date(),
                    end=(datetime.now(UTC) + timedelta(days=7)).date(),
                ),
                duration_minutes=60,
            )


# --- Compliance gates ------------------------------------------------------------------


async def test_exclusion_check_blocks_medicaid_assignment(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    """PRD US-1.3.2: this is a hard system gate, not a warning."""
    visit_id = await _seed_visit(tenant_a)

    async with tenant_session(tenant_a.agency_id) as session:
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        caregiver.exclusion_check_status = ExclusionCheckStatus.not_run
        await session.flush()

        visit = await session.get(ScheduledVisit, visit_id)
        with pytest.raises(ComplianceGateError) as exc:
            await scheduling.assign_caregiver(
                session, principal=tenant_a.principal(), visit=visit, caregiver=caregiver
            )
    assert "exclusion check" in str(exc.value).lower()
    assert exc.value.code == "COMPLIANCE_GATE_FAILED"


async def test_flagged_exclusion_also_blocks(tenant_a: TenantFixture, reference_data: None) -> None:
    visit_id = await _seed_visit(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        caregiver.exclusion_check_status = ExclusionCheckStatus.flagged
        await session.flush()
        visit = await session.get(ScheduledVisit, visit_id)
        with pytest.raises(ComplianceGateError):
            await scheduling.assign_caregiver(
                session, principal=tenant_a.principal(), visit=visit, caregiver=caregiver
            )


async def test_private_pay_visit_does_not_require_exclusion_check(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    """The gate is scoped to publicly-funded payers, where the legal exposure sits."""
    visit_id = await _seed_visit(tenant_a, payer_type="private_pay", service_code=None)

    async with tenant_session(tenant_a.agency_id) as session:
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        caregiver.exclusion_check_status = ExclusionCheckStatus.not_run
        await session.flush()
        visit = await session.get(ScheduledVisit, visit_id)
        assigned = await scheduling.assign_caregiver(
            session, principal=tenant_a.principal(), visit=visit, caregiver=caregiver
        )
    assert assigned.status is VisitStatus.assigned


async def test_credential_expiring_before_service_date_blocks_assignment(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    """Checked against the visit's date, not today — that is the error worth catching."""
    visit_id = await _seed_visit(tenant_a)

    async with tenant_session(tenant_a.agency_id) as session:
        visit = await session.get(ScheduledVisit, visit_id)
        session.add(
            Credential(
                agency_id=tenant_a.agency_id,
                caregiver_id=tenant_a.caregiver_id,
                credential_type="HHA",
                verification_status=VerificationStatus.verified,
                expiration_date=visit.scheduled_start.date() - timedelta(days=1),
            )
        )
        await session.flush()

        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        with pytest.raises(ComplianceGateError) as exc:
            await scheduling.assign_caregiver(
                session, principal=tenant_a.principal(), visit=visit, caregiver=caregiver
            )
    assert "expire" in str(exc.value).lower()


async def test_terminated_caregiver_cannot_be_assigned(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    visit_id = await _seed_visit(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        caregiver.employment_status = EmploymentStatus.terminated
        await session.flush()
        visit = await session.get(ScheduledVisit, visit_id)
        with pytest.raises(ComplianceGateError):
            await scheduling.assign_caregiver(
                session, principal=tenant_a.principal(), visit=visit, caregiver=caregiver
            )


async def test_double_booking_is_refused(tenant_a: TenantFixture, reference_data: None) -> None:
    """A caregiver in two homes at once produces EVV records the state will reject."""
    _client_id, plan_id = await make_client_with_plan(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        plan = await session.get(CarePlan, plan_id)
        visits = await scheduling.generate_visits(
            session,
            principal=tenant_a.principal(),
            care_plan=plan,
            window=scheduling.GenerationWindow(
                start=datetime.now(UTC).date(),
                end=(datetime.now(UTC) + timedelta(days=7)).date(),
            ),
            duration_minutes=60,
        )
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        await scheduling.assign_caregiver(
            session, principal=tenant_a.principal(), visit=visits[0], caregiver=caregiver
        )
        # Force an exact overlap with the first visit.
        visits[1].scheduled_start = visits[0].scheduled_start
        visits[1].scheduled_end = visits[0].scheduled_end
        await session.flush()

        with pytest.raises(ConflictError, match="overlapping"):
            await scheduling.assign_caregiver(
                session, principal=tenant_a.principal(), visit=visits[1], caregiver=caregiver
            )


# --- Clock in / out --------------------------------------------------------------------


async def test_clock_in_and_out_golden_path(tenant_a: TenantFixture, reference_data: None) -> None:
    visit_id = await _seed_visit(tenant_a)
    now = datetime.now(UTC)

    async with tenant_session(tenant_a.agency_id) as session:
        visit = await session.get(ScheduledVisit, visit_id)
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        await scheduling.assign_caregiver(
            session, principal=tenant_a.principal(), visit=visit, caregiver=caregiver
        )
        record = await scheduling.clock_in(
            session,
            principal=tenant_a.principal(),
            visit=visit,
            timestamp=now,
            capture_method=CaptureMethod.mobile_gps,
            lat=40.7128,
            lng=-74.0060,
        )
        assert visit.status is VisitStatus.in_progress
        assert record.transmission_status is TransmissionStatus.pending

        await scheduling.clock_out(
            session,
            principal=tenant_a.principal(),
            visit=visit,
            timestamp=now + timedelta(hours=1),
            lat=40.7128,
            lng=-74.0060,
        )
        assert visit.status is VisitStatus.completed


async def test_offline_replay_of_clock_in_is_idempotent(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    """The mobile app replays queued actions on reconnect; a replay is not a second visit."""
    visit_id = await _seed_visit(tenant_a)
    local_uuid = "offline-abc-123"
    now = datetime.now(UTC)

    async with tenant_session(tenant_a.agency_id) as session:
        visit = await session.get(ScheduledVisit, visit_id)
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        await scheduling.assign_caregiver(
            session, principal=tenant_a.principal(), visit=visit, caregiver=caregiver
        )
        first = await scheduling.clock_in(
            session,
            principal=tenant_a.principal(),
            visit=visit,
            timestamp=now,
            capture_method=CaptureMethod.mobile_gps,
            lat=40.7,
            lng=-74.0,
            client_local_uuid=local_uuid,
        )
        replay = await scheduling.clock_in(
            session,
            principal=tenant_a.principal(),
            visit=visit,
            timestamp=now,
            capture_method=CaptureMethod.mobile_gps,
            lat=40.7,
            lng=-74.0,
            client_local_uuid=local_uuid,
        )
        assert first.id == replay.id

        count = len(
            (
                await session.execute(
                    select(EVVRecord).where(EVVRecord.scheduled_visit_id == visit.id)
                )
            )
            .scalars()
            .all()
        )
        assert count == 1


async def test_second_distinct_clock_in_is_refused(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    visit_id = await _seed_visit(tenant_a)
    now = datetime.now(UTC)
    async with tenant_session(tenant_a.agency_id) as session:
        visit = await session.get(ScheduledVisit, visit_id)
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        await scheduling.assign_caregiver(
            session, principal=tenant_a.principal(), visit=visit, caregiver=caregiver
        )
        await scheduling.clock_in(
            session,
            principal=tenant_a.principal(),
            visit=visit,
            timestamp=now,
            capture_method=CaptureMethod.mobile_gps,
            client_local_uuid="first",
        )
        with pytest.raises(ConflictError):
            await scheduling.clock_in(
                session,
                principal=tenant_a.principal(),
                visit=visit,
                timestamp=now,
                capture_method=CaptureMethod.mobile_gps,
                client_local_uuid="second",
            )


async def test_clock_out_without_clock_in_is_refused(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    visit_id = await _seed_visit(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        visit = await session.get(ScheduledVisit, visit_id)
        with pytest.raises(ConflictError):
            await scheduling.clock_out(
                session,
                principal=tenant_a.principal(),
                visit=visit,
                timestamp=datetime.now(UTC),
            )


# --- EVV payload and transmission -------------------------------------------------------


def test_evv_payload_requires_all_six_elements() -> None:
    """A payload missing a federally required element must fail before transmission."""
    base = {
        "visit_id": uuid.uuid4(),
        "agency_id": uuid.uuid4(),
        "state_code": "NY",
        "service_type_code": "T1019",
        "client_id": uuid.uuid4(),
        "client_name": "Client",
        "service_date": "2026-07-29",
        "location": {"coordinates": {"lat": 40.7, "lng": -74.0}},
        "caregiver_id": uuid.uuid4(),
        "caregiver_name": "Caregiver",
        "service_start": datetime.now(UTC),
        "service_end": datetime.now(UTC) + timedelta(hours=1),
        "capture_method": "mobile_gps",
    }
    EVVPayload(**base)  # complete payload constructs fine

    with pytest.raises(EVVElementError, match="service_type_code"):
        EVVPayload(**{**base, "service_type_code": ""})
    with pytest.raises(EVVElementError, match="client_name"):
        EVVPayload(**{**base, "client_name": ""})


def test_evv_payload_requires_location_or_a_documented_reason() -> None:
    """Element 4 may lack coordinates only when the absence is explained."""
    base = {
        "visit_id": uuid.uuid4(),
        "agency_id": uuid.uuid4(),
        "state_code": "NY",
        "service_type_code": "T1019",
        "client_id": uuid.uuid4(),
        "client_name": "Client",
        "service_date": "2026-07-29",
        "caregiver_id": uuid.uuid4(),
        "caregiver_name": "Caregiver",
        "service_start": datetime.now(UTC),
        "service_end": datetime.now(UTC) + timedelta(hours=1),
        "capture_method": "telephony",
    }
    with pytest.raises(EVVElementError, match="absence_reason"):
        EVVPayload(**base, location={})

    # Telephony capture with a stated reason is a compliant record.
    EVVPayload(**base, location={"absence_reason": "telephony_capture"})


def test_canonical_snapshot_uses_federal_element_names() -> None:
    payload = EVVPayload(
        visit_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        state_code="NY",
        service_type_code="T1019",
        client_id=uuid.uuid4(),
        client_name="Ada Client",
        service_date="2026-07-29",
        location={"coordinates": {"lat": 40.7, "lng": -74.0}},
        caregiver_id=uuid.uuid4(),
        caregiver_name="Grace Caregiver",
        service_start=datetime(2026, 7, 29, 9, tzinfo=UTC),
        service_end=datetime(2026, 7, 29, 10, tzinfo=UTC),
        capture_method="mobile_gps",
    )
    snapshot = payload.as_canonical_snapshot()
    assert set(snapshot) >= {
        "type_of_service",
        "individual_receiving_service",
        "date_of_service",
        "location_of_service",
        "individual_providing_service",
        "service_begin_time",
        "service_end_time",
    }


async def test_transmission_marks_record_acknowledged_and_snapshots(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    """Only acknowledgement makes a visit compliant, and the snapshot is written once."""
    visit_id = await _seed_visit(tenant_a)
    now = datetime.now(UTC)

    async with tenant_session(tenant_a.agency_id) as session:
        visit = await session.get(ScheduledVisit, visit_id)
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        await scheduling.assign_caregiver(
            session, principal=tenant_a.principal(), visit=visit, caregiver=caregiver
        )
        await scheduling.clock_in(
            session,
            principal=tenant_a.principal(),
            visit=visit,
            timestamp=now,
            capture_method=CaptureMethod.mobile_gps,
            lat=40.7128,
            lng=-74.0060,
        )
        record = await scheduling.clock_out(
            session,
            principal=tenant_a.principal(),
            visit=visit,
            timestamp=now + timedelta(hours=1),
            lat=40.7128,
            lng=-74.0060,
        )

        record = await scheduling.transmit_evv_record(
            session, principal=tenant_a.principal(), visit=visit, record=record
        )

    assert record.transmission_status is TransmissionStatus.acknowledged
    assert record.transmission_attempts == 1
    assert record.aggregator_key == "loopback"
    assert record.six_element_snapshot is not None
    assert record.six_element_snapshot["type_of_service"] == "T1019"


async def test_transient_failure_leaves_record_retryable(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    """An aggregator outage must not lose the visit — the record stays pending."""
    adapter = LoopbackAdapter(outcome=TransmissionOutcome.transient_failure)
    visit_id = await _seed_visit(tenant_a)
    now = datetime.now(UTC)

    async with tenant_session(tenant_a.agency_id) as session:
        visit = await session.get(ScheduledVisit, visit_id)
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        await scheduling.assign_caregiver(
            session, principal=tenant_a.principal(), visit=visit, caregiver=caregiver
        )
        await scheduling.clock_in(
            session,
            principal=tenant_a.principal(),
            visit=visit,
            timestamp=now,
            capture_method=CaptureMethod.mobile_gps,
            lat=40.7128,
            lng=-74.0060,
        )
        record = await scheduling.clock_out(
            session,
            principal=tenant_a.principal(),
            visit=visit,
            timestamp=now + timedelta(hours=1),
        )
        payload = await scheduling.build_evv_payload(session, visit=visit, record=record)
        result = await adapter.submit(payload)

    assert result.is_retryable
    assert not result.is_compliant
    assert record.transmission_status is TransmissionStatus.pending


async def test_registry_refuses_an_unconfigured_state(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    """No safe default exists: transmitting to the wrong aggregator looks like success."""
    from careos.core.errors import EVVTransmissionError

    async with tenant_session(tenant_a.agency_id) as session:
        with pytest.raises(EVVTransmissionError, match="No EVV aggregator"):
            await resolve_for_state(session, "ZZ")


async def test_registry_resolves_the_configured_adapter(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    async with tenant_session(tenant_a.agency_id) as session:
        adapter = await resolve_for_state(session, "ny")  # case-insensitive
    assert adapter.adapter_key == "loopback"
