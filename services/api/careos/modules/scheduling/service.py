"""Scheduling and EVV domain logic.

Everything compliance-critical in Phase 1 lives here rather than in the routers, so the
gates hold regardless of which surface calls them — admin web, caregiver mobile, or a
future bulk import.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from dateutil.rrule import rrulestr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core.audit import AuditAction, record_audit
from careos.core.errors import ComplianceGateError, ConflictError, NotFoundError
from careos.core.security import Principal
from careos.integrations.evv import registry
from careos.integrations.evv.base import EVVPayload, TransmissionOutcome
from careos.modules.compliance_rules import engine as rules_engine
from careos.modules.compliance_rules.engine import Finding, Severity
from careos.modules.credentialing.models import Caregiver, Credential, ExclusionCheckStatus
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

#: Payer types whose visits are publicly funded, and therefore subject to the OIG/GSA
#: exclusion gate in PRD US-1.3.2.
PUBLICLY_FUNDED_PAYER_TYPES = frozenset({"medicaid_waiver", "medicare_advantage"})

#: Cap on visits materialized in a single call, so a malformed recurrence rule cannot
#: generate an unbounded number of rows.
MAX_GENERATED_VISITS = 500


# --------------------------------------------------------------------------------------
# Compliance gates
# --------------------------------------------------------------------------------------


async def assert_assignable(
    session: AsyncSession,
    *,
    caregiver: Caregiver,
    visit: ScheduledVisit,
) -> None:
    """Hard gate: may this caregiver be assigned to this visit?

    PRD US-1.3.2 is unambiguous that the exclusion-list check is "a hard system gate, not a
    warning". Assigning an excluded individual to a Medicaid-billed visit exposes the agency
    to recoupment and false-claims liability, so this raises rather than flags.

    Credential expiry is checked against the visit's service date, not today: assigning
    someone to a visit three weeks out whose certification lapses next week is exactly the
    error this is meant to catch.
    """
    if caregiver.employment_status.value in {"terminated", "inactive"}:
        raise ComplianceGateError(
            "Caregiver is not in an active employment status",
            details={"employment_status": caregiver.employment_status.value},
        )

    payer_type = visit.payer_type
    if payer_type in PUBLICLY_FUNDED_PAYER_TYPES and not caregiver.is_exclusion_cleared:
        raise ComplianceGateError(
            "Caregiver cannot be scheduled for a publicly-funded visit until the OIG/GSA "
            "exclusion check has cleared",
            details={
                "exclusion_check_status": caregiver.exclusion_check_status.value,
                "payer_type": payer_type,
                "rule": "PRD US-1.3.2",
            },
        )

    service_date = visit.scheduled_start.date()
    credentials = (
        (await session.execute(select(Credential).where(Credential.caregiver_id == caregiver.id)))
        .scalars()
        .all()
    )

    # Collect (type, expiry) pairs rather than the ORM objects, so the not-None narrowing
    # happens once here instead of being re-asserted where the detail payload is built.
    expired: list[tuple[str, date]] = [
        (c.credential_type, c.expiration_date)
        for c in credentials
        if c.expiration_date is not None and c.expiration_date < service_date
    ]
    if expired:
        raise ComplianceGateError(
            "Caregiver holds credentials that expire before this visit's service date",
            details={
                "service_date": service_date.isoformat(),
                "expired_credentials": [
                    {"type": credential_type, "expires": expires.isoformat()}
                    for credential_type, expires in expired
                ],
            },
        )


# --------------------------------------------------------------------------------------
# Visit generation
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class GenerationWindow:
    start: date
    end: date


def _materialize_occurrences(
    rule: dict[str, Any], window: GenerationWindow, plan_start: date
) -> list[datetime]:
    """Expand a recurrence rule into concrete start datetimes.

    Accepts an iCalendar RRULE string, which is what `care_plan.visit_frequency_rule` holds
    (`04_Data_Model_and_Schema.md` describes it as "RRULE-style"). Using the standard rather
    than a bespoke frequency format means weekly-on-Mon/Wed/Fri and every-other-week
    schedules — both common in home care — need no special handling.
    """
    rrule_text = rule.get("rrule")
    if not rrule_text:
        raise ConflictError(
            "Care plan has no recurrence rule, so visits cannot be generated",
            details={"expected": "visit_frequency_rule.rrule (an iCalendar RRULE string)"},
        )

    start_hour = int(rule.get("start_hour", 9))
    start_minute = int(rule.get("start_minute", 0))
    dtstart = datetime.combine(
        max(window.start, plan_start),
        datetime.min.time().replace(hour=start_hour, minute=start_minute),
        tzinfo=UTC,
    )
    window_end = datetime.combine(window.end, datetime.max.time(), tzinfo=UTC)

    try:
        occurrences = list(
            rrulestr(rrule_text, dtstart=dtstart).between(dtstart, window_end, inc=True)
        )
    except (ValueError, TypeError) as exc:
        raise ConflictError(
            f"Care plan recurrence rule is not a valid RRULE: {exc}",
            details={"rrule": rrule_text},
        ) from exc

    if len(occurrences) > MAX_GENERATED_VISITS:
        raise ConflictError(
            f"Recurrence rule would generate {len(occurrences)} visits, above the "
            f"{MAX_GENERATED_VISITS} limit for a single call",
            details={"generated": len(occurrences), "limit": MAX_GENERATED_VISITS},
        )
    return occurrences


async def generate_visits(
    session: AsyncSession,
    *,
    principal: Principal,
    care_plan: CarePlan,
    window: GenerationWindow,
    duration_minutes: int,
) -> list[ScheduledVisit]:
    """Materialize `scheduled_visit` rows from a care plan's recurrence rule.

    Visits inherit the plan's service code and the client's state and payer type at
    generation time. That denormalization is deliberate — see `ScheduledVisit`'s docstring.
    """
    client = await session.get(Client, care_plan.client_id)
    if client is None:
        raise NotFoundError("Care plan references a client that does not exist")

    occurrences = _materialize_occurrences(
        care_plan.visit_frequency_rule, window, care_plan.effective_start
    )

    # A regenerate over an overlapping window must not duplicate visits already created.
    existing_starts = set(
        (
            await session.execute(
                select(ScheduledVisit.scheduled_start).where(
                    ScheduledVisit.care_plan_id == care_plan.id
                )
            )
        )
        .scalars()
        .all()
    )

    created: list[ScheduledVisit] = []
    for start in occurrences:
        if care_plan.effective_end and start.date() > care_plan.effective_end:
            continue
        if start in existing_starts:
            continue
        visit = ScheduledVisit(
            agency_id=care_plan.agency_id,
            care_plan_id=care_plan.id,
            scheduled_start=start,
            scheduled_end=start + timedelta(minutes=duration_minutes),
            status=VisitStatus.open,
            service_type_code=care_plan.default_service_type_code,
            service_state=client.service_state,
            payer_type=client.primary_payer_type,
            required_tasks=care_plan.authorized_tasks,
        )
        session.add(visit)
        created.append(visit)

    await session.flush()
    await record_audit(
        session,
        principal=principal,
        agency_id=care_plan.agency_id,
        action=AuditAction.visits_generated,
        entity_type="care_plan",
        entity_id=care_plan.id,
        after_state={
            "generated_count": len(created),
            "window": [window.start.isoformat(), window.end.isoformat()],
        },
    )
    return created


async def assign_caregiver(
    session: AsyncSession,
    *,
    principal: Principal,
    visit: ScheduledVisit,
    caregiver: Caregiver,
) -> ScheduledVisit:
    """Assign a caregiver to a visit, after the compliance gates pass."""
    await assert_assignable(session, caregiver=caregiver, visit=visit)

    if visit.status in {VisitStatus.completed, VisitStatus.cancelled}:
        raise ConflictError(
            "Cannot assign a caregiver to a visit that is already completed or cancelled",
            details={"status": visit.status.value},
        )

    # Double-booking check. A caregiver physically cannot be in two homes at once, and a
    # schedule that claims otherwise produces two EVV records the state will reject.
    overlapping = (
        (
            await session.execute(
                select(ScheduledVisit.id).where(
                    ScheduledVisit.caregiver_id == caregiver.id,
                    ScheduledVisit.id != visit.id,
                    ScheduledVisit.status.notin_([VisitStatus.cancelled, VisitStatus.missed]),
                    ScheduledVisit.scheduled_start < visit.scheduled_end,
                    ScheduledVisit.scheduled_end > visit.scheduled_start,
                )
            )
        )
        .scalars()
        .first()
    )
    if overlapping is not None:
        raise ConflictError(
            "Caregiver is already assigned to an overlapping visit",
            details={"conflicting_visit_id": str(overlapping)},
        )

    before = {
        "caregiver_id": str(visit.caregiver_id) if visit.caregiver_id else None,
        "status": visit.status.value,
    }
    visit.caregiver_id = caregiver.id
    visit.status = VisitStatus.assigned
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=visit.agency_id,
        action=AuditAction.visit_assigned,
        entity_type="scheduled_visit",
        entity_id=visit.id,
        before_state=before,
        after_state={"caregiver_id": str(caregiver.id), "status": visit.status.value},
    )
    return visit


# --------------------------------------------------------------------------------------
# Clock in / out and EVV transmission
# --------------------------------------------------------------------------------------


async def clock_in(
    session: AsyncSession,
    *,
    principal: Principal,
    visit: ScheduledVisit,
    timestamp: datetime,
    capture_method: CaptureMethod,
    lat: float | None = None,
    lng: float | None = None,
    client_local_uuid: str | None = None,
) -> EVVRecord:
    """Record a clock-in, creating the visit's EVV record.

    Clock-in is never refused for a compliance reason. `02_Product_Requirements_Document.md`
    US-1.4.3 and the availability NFR treat this as a legally time-sensitive action, and
    `05_API_Specification.md` Section 9 exempts it even from rate limiting. A caregiver
    standing in a client's home must always be able to record that they are there; problems
    with the visit surface as compliance exceptions afterwards, not as a blocked clock-in.
    """
    if visit.caregiver_id is None:
        raise ConflictError("Cannot clock in to a visit with no assigned caregiver")

    existing = (
        await session.execute(select(EVVRecord).where(EVVRecord.scheduled_visit_id == visit.id))
    ).scalar_one_or_none()

    if existing is not None:
        # The mobile app replays queued actions on reconnect. A replay carrying the same
        # locally-generated UUID is the same clock-in, not a second one.
        if client_local_uuid and existing.client_local_uuid == client_local_uuid:
            return existing
        raise ConflictError(
            "This visit already has a clock-in recorded",
            details={"evv_record_id": str(existing.id)},
        )

    record = EVVRecord(
        agency_id=visit.agency_id,
        scheduled_visit_id=visit.id,
        clock_in_time=timestamp,
        clock_in_lat=lat,
        clock_in_lng=lng,
        capture_method=capture_method,
        transmission_status=TransmissionStatus.pending,
        client_local_uuid=client_local_uuid,
    )
    session.add(record)
    visit.status = VisitStatus.in_progress
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=visit.agency_id,
        action=AuditAction.visit_clock_in,
        entity_type="evv_record",
        entity_id=record.id,
        after_state={
            "visit_id": str(visit.id),
            "clock_in_time": timestamp.isoformat(),
            "capture_method": capture_method.value,
        },
    )
    return record


async def clock_out(
    session: AsyncSession,
    *,
    principal: Principal,
    visit: ScheduledVisit,
    timestamp: datetime,
    lat: float | None = None,
    lng: float | None = None,
    client_local_uuid: str | None = None,
) -> EVVRecord:
    """Record a clock-out and mark the visit complete.

    Transmission is deliberately *not* done here. It is a network call to a third party and
    must not sit between the caregiver and a completed clock-out — see
    :func:`transmit_evv_record`, which the queue worker drives.
    """
    record = (
        await session.execute(select(EVVRecord).where(EVVRecord.scheduled_visit_id == visit.id))
    ).scalar_one_or_none()
    if record is None:
        raise ConflictError("Cannot clock out of a visit with no recorded clock-in")

    if record.clock_out_time is not None:
        if client_local_uuid and record.client_local_uuid == client_local_uuid:
            return record
        raise ConflictError(
            "This visit already has a clock-out recorded",
            details={"evv_record_id": str(record.id)},
        )
    if record.clock_in_time and timestamp < record.clock_in_time:
        raise ConflictError("Clock-out time precedes clock-in time")

    record.clock_out_time = timestamp
    record.clock_out_lat = lat
    record.clock_out_lng = lng
    visit.status = VisitStatus.completed
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=visit.agency_id,
        action=AuditAction.visit_clock_out,
        entity_type="evv_record",
        entity_id=record.id,
        after_state={"visit_id": str(visit.id), "clock_out_time": timestamp.isoformat()},
    )
    return record


async def build_evv_payload(
    session: AsyncSession, *, visit: ScheduledVisit, record: EVVRecord
) -> EVVPayload:
    """Assemble the six federally required elements for transmission."""
    care_plan = await session.get(CarePlan, visit.care_plan_id)
    if care_plan is None:
        raise NotFoundError("Visit references a care plan that does not exist")
    client = await session.get(Client, care_plan.client_id)
    caregiver = await session.get(Caregiver, visit.caregiver_id) if visit.caregiver_id else None
    if client is None or caregiver is None:
        raise NotFoundError("Visit is missing its client or caregiver record")

    if record.clock_in_time is None or record.clock_out_time is None:
        raise ConflictError("EVV record is incomplete; both clock-in and clock-out are required")

    # Element 4 — location. Coordinates where we have them; otherwise the documented reason
    # they are absent, which is what makes a telephony capture a compliant record rather
    # than an incomplete one.
    if record.clock_in_lat is not None and record.clock_in_lng is not None:
        location = {
            "coordinates": {
                "lat": float(record.clock_in_lat),
                "lng": float(record.clock_in_lng),
            },
            "capture_method": record.capture_method.value,
        }
    else:
        location = {
            "absence_reason": (
                "telephony_capture"
                if record.capture_method is CaptureMethod.telephony
                else "manual_exception"
            ),
            "capture_method": record.capture_method.value,
        }

    return EVVPayload(
        visit_id=visit.id,
        agency_id=visit.agency_id,
        state_code=(visit.service_state or client.service_state),
        service_type_code=visit.service_type_code or "",
        client_id=client.id,
        client_name=client.legal_name,
        service_date=record.clock_in_time.date().isoformat(),
        location=location,
        caregiver_id=caregiver.id,
        caregiver_name=caregiver.legal_name,
        service_start=record.clock_in_time,
        service_end=record.clock_out_time,
        capture_method=record.capture_method.value,
    )


async def transmit_evv_record(
    session: AsyncSession,
    *,
    principal: Principal | None,
    visit: ScheduledVisit,
    record: EVVRecord,
) -> EVVRecord:
    """Transmit one EVV record to the state aggregator and record the outcome.

    Called by the transmission worker, not by the clock-out request path. Failures are
    recorded rather than raised: a transient aggregator outage must leave a retryable row,
    not lose the visit.
    """
    payload = await build_evv_payload(session, visit=visit, record=record)
    adapter = await registry.resolve_for_state(session, payload.state_code)

    result = await adapter.submit(payload)

    record.transmission_attempts += 1
    record.last_transmission_at = datetime.now(UTC)
    record.aggregator_key = adapter.adapter_key
    record.aggregator_response_payload = result.raw_response
    # Written once, at transmission time: this is what the state saw, and it must not drift
    # as the underlying rows change.
    if record.six_element_snapshot is None:
        record.six_element_snapshot = payload.as_canonical_snapshot()

    if result.outcome is TransmissionOutcome.accepted:
        record.transmission_status = TransmissionStatus.acknowledged
        action = AuditAction.evv_acknowledged
    elif result.outcome is TransmissionOutcome.submitted:
        record.transmission_status = TransmissionStatus.transmitted
        action = AuditAction.evv_transmitted
    elif result.outcome is TransmissionOutcome.rejected:
        record.transmission_status = TransmissionStatus.rejected
        action = AuditAction.evv_rejected
    else:
        # Transient: leave the status alone so the worker picks it up again.
        action = AuditAction.evv_transmitted

    await session.flush()
    await record_audit(
        session,
        principal=principal,
        agency_id=visit.agency_id,
        action=action,
        entity_type="evv_record",
        entity_id=record.id,
        after_state={
            "transmission_status": record.transmission_status.value,
            "outcome": result.outcome.value,
            "attempts": record.transmission_attempts,
            "aggregator": adapter.adapter_key,
        },
    )
    return record


# --------------------------------------------------------------------------------------
# Compliance evaluation
# --------------------------------------------------------------------------------------


async def build_visit_rule_context(
    session: AsyncSession, *, visit: ScheduledVisit
) -> dict[str, Any]:
    """Flatten a visit and its related rows into the dict the rules engine consumes."""
    record = (
        await session.execute(select(EVVRecord).where(EVVRecord.scheduled_visit_id == visit.id))
    ).scalar_one_or_none()
    care_plan = await session.get(CarePlan, visit.care_plan_id)
    client = await session.get(Client, care_plan.client_id) if care_plan else None
    caregiver = await session.get(Caregiver, visit.caregiver_id) if visit.caregiver_id else None

    credentials: Sequence[Credential] = ()
    if caregiver is not None:
        credentials = (
            (
                await session.execute(
                    select(Credential).where(Credential.caregiver_id == caregiver.id)
                )
            )
            .scalars()
            .all()
        )

    return {
        "entity_id": visit.id,
        "visit_status": visit.status.value,
        "service_type_code": visit.service_type_code,
        "payer_type": visit.payer_type,
        "service_date": visit.scheduled_start.date(),
        "clock_in_time": record.clock_in_time if record else None,
        "clock_out_time": record.clock_out_time if record else None,
        "clock_in_lat": float(record.clock_in_lat) if record and record.clock_in_lat else None,
        "clock_in_lng": float(record.clock_in_lng) if record and record.clock_in_lng else None,
        "capture_method": record.capture_method.value if record else None,
        "transmission_status": record.transmission_status.value if record else None,
        "aggregator_response": record.aggregator_response_payload if record else None,
        "client_lat": float(client.geo_lat) if client and client.geo_lat else None,
        "client_lng": float(client.geo_lng) if client and client.geo_lng else None,
        "exclusion_check_status": (
            caregiver.exclusion_check_status.value
            if caregiver
            else ExclusionCheckStatus.not_run.value
        ),
        "caregiver_credentials": [
            {"credential_type": c.credential_type, "expiration_date": c.expiration_date}
            for c in credentials
        ],
    }


async def evaluate_visit_compliance(
    session: AsyncSession,
    *,
    principal: Principal | None,
    visit: ScheduledVisit,
) -> list[Finding]:
    """Run the visit rule set and reconcile the results into `compliance_exception`.

    Reconciles rather than appends: findings that no longer fire are resolved, so the
    exception queue reflects current state. `09_UX_Design_and_User_Flows.md` principle 3
    puts exception queues in front of schedulers as their default view — a queue that only
    ever grows is one they stop reading.
    """
    context = await build_visit_rule_context(session, visit=visit)
    findings = rules_engine.evaluate("visit", context)
    found_keys = {f.rule_key for f in findings}

    open_exceptions = (
        (
            await session.execute(
                select(ComplianceException).where(
                    ComplianceException.entity_type == "visit",
                    ComplianceException.entity_id == visit.id,
                    ComplianceException.resolved_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    open_by_key = {e.rule_key: e for e in open_exceptions}

    now = datetime.now(UTC)
    for existing in open_exceptions:
        if existing.rule_key not in found_keys:
            existing.resolved_at = now

    for finding in findings:
        if finding.rule_key in open_by_key:
            existing = open_by_key[finding.rule_key]
            existing.severity = finding.severity.value
            existing.message = finding.message
            existing.details = finding.details
            continue
        session.add(
            ComplianceException(
                agency_id=visit.agency_id,
                rule_key=finding.rule_key,
                severity=finding.severity.value,
                entity_type="visit",
                entity_id=visit.id,
                message=finding.message,
                details=finding.details,
            )
        )

    await session.flush()

    if findings and principal is not None:
        await record_audit(
            session,
            principal=principal,
            agency_id=visit.agency_id,
            action=AuditAction.compliance_exception_raised,
            entity_type="scheduled_visit",
            entity_id=visit.id,
            after_state={
                "findings": [
                    {"rule_key": f.rule_key, "severity": f.severity.value} for f in findings
                ]
            },
        )
    return findings


def critical_findings(findings: Sequence[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity is Severity.critical]


__all__ = [
    "GenerationWindow",
    "assert_assignable",
    "assign_caregiver",
    "build_evv_payload",
    "build_visit_rule_context",
    "clock_in",
    "clock_out",
    "critical_findings",
    "evaluate_visit_compliance",
    "generate_visits",
    "transmit_evv_record",
]
