"""Visits, assignment, and EVV clock-in/out (`05_API_Specification.md` Section 4).

The clock-in and clock-out endpoints are the highest-stakes surface in Phase 1. Three
properties they must keep:

* They require an `Idempotency-Key`, because the mobile app replays queued actions after
  working offline and a duplicate EVV transmission is a compliance problem.
* They are exempt from ordinary rate limiting (Section 9) — never throttle a legally
  time-sensitive action.
* They do not block on compliance problems. Findings are returned alongside a successful
  clock-out so the caregiver is never stuck in a client's home arguing with the app.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.api import schemas
from careos.api.deps import db_session
from careos.core import idempotency
from careos.core.audit import AuditAction, record_audit
from careos.core.errors import NotFoundError, PermissionDeniedError
from careos.core.rbac import requires
from careos.core.security import Principal
from careos.modules.agency.models import Role
from careos.modules.compliance_rules import engine as rules_engine
from careos.modules.credentialing.models import Caregiver
from careos.modules.scheduling import exceptions_service, matching
from careos.modules.scheduling import service as scheduling_service
from careos.modules.scheduling.models import (
    CaptureMethod,
    EVVRecord,
    ScheduledVisit,
    TransmissionStatus,
    VisitStatus,
)

router = APIRouter(tags=["visits"])


async def _load_visit(
    session: AsyncSession, visit_id: uuid.UUID, principal: Principal
) -> ScheduledVisit:
    visit = await session.get(ScheduledVisit, visit_id)
    if visit is None:
        raise NotFoundError("Visit not found")
    # Minimum-necessary access (HIPAA; `08_Security_Architecture.md` Section 1): a caregiver
    # may only reach visits assigned to them, not the agency's whole schedule.
    if principal.role is Role.caregiver and visit.caregiver_id != principal.caregiver_id:
        raise PermissionDeniedError("You can only access visits assigned to you")
    return visit


def _evv_status_out(record: EVVRecord) -> schemas.EVVStatusOut:
    return schemas.EVVStatusOut(
        id=record.id,
        scheduled_visit_id=record.scheduled_visit_id,
        clock_in_time=record.clock_in_time,
        clock_out_time=record.clock_out_time,
        capture_method=record.capture_method.value,
        transmission_status=record.transmission_status.value,
        transmission_attempts=record.transmission_attempts,
        aggregator_key=record.aggregator_key,
        is_compliant=record.transmission_status is TransmissionStatus.acknowledged,
    )


@router.get("/visits", response_model=schemas.VisitPage)
async def list_visits(
    principal: Principal = Depends(
        requires(
            Role.owner_admin, Role.scheduler, Role.clinical_supervisor, Role.caregiver, Role.auditor
        )
    ),
    session: AsyncSession = Depends(db_session),
    status_filter: VisitStatus | None = Query(default=None, alias="status"),
    caregiver_id: uuid.UUID | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> schemas.VisitPage:
    filters = []
    if status_filter is not None:
        filters.append(ScheduledVisit.status == status_filter)
    if caregiver_id is not None:
        filters.append(ScheduledVisit.caregiver_id == caregiver_id)
    if date_from is not None:
        filters.append(func.date(ScheduledVisit.scheduled_start) >= date_from)
    if date_to is not None:
        filters.append(func.date(ScheduledVisit.scheduled_start) <= date_to)

    # A caregiver's list is narrowed to their own visits regardless of the query they sent.
    if principal.role is Role.caregiver:
        filters.append(ScheduledVisit.caregiver_id == principal.caregiver_id)

    total = (
        await session.execute(select(func.count()).select_from(ScheduledVisit).where(*filters))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(ScheduledVisit)
                .where(*filters)
                .order_by(ScheduledVisit.scheduled_start)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    return schemas.VisitPage(
        items=[schemas.VisitOut.model_validate(v) for v in rows],
        page=schemas.Page(page=page, page_size=page_size, total=total),
    )


# Registered before /visits/{visit_id}: FastAPI matches routes in declaration order, so a
# literal segment must be declared ahead of the parameterized one or "gaps" is parsed as
# a visit id and rejected as a malformed UUID.
@router.get("/visits/gaps", response_model=list[schemas.VisitOut])
async def open_gaps(
    principal: Principal = Depends(requires(Role.owner_admin, Role.scheduler)),
    session: AsyncSession = Depends(db_session),
    within_hours: int = Query(default=48, ge=1, le=24 * 30),
) -> list[schemas.VisitOut]:
    """Unfilled visits starting soon, soonest first (US-1.4.4)."""
    gaps = await matching.detect_gaps(session, within_hours=within_hours)
    return [schemas.VisitOut.model_validate(v) for v in gaps]


@router.get("/visits/{visit_id}", response_model=schemas.VisitOut)
async def get_visit(
    visit_id: uuid.UUID,
    principal: Principal = Depends(
        requires(
            Role.owner_admin, Role.scheduler, Role.clinical_supervisor, Role.caregiver, Role.auditor
        )
    ),
    session: AsyncSession = Depends(db_session),
) -> schemas.VisitOut:
    visit = await _load_visit(session, visit_id, principal)
    return schemas.VisitOut.model_validate(visit)


@router.post("/visits/{visit_id}/assign", response_model=schemas.VisitOut)
async def assign(
    visit_id: uuid.UUID,
    payload: schemas.AssignRequest,
    principal: Principal = Depends(requires(Role.owner_admin, Role.scheduler)),
    session: AsyncSession = Depends(db_session),
) -> schemas.VisitOut:
    """Assign a caregiver, subject to the hard compliance gates in the scheduling service.

    A caregiver without a cleared OIG/GSA exclusion check is refused outright for a
    publicly-funded visit (PRD US-1.3.2), returning `COMPLIANCE_GATE_FAILED`.
    """
    visit = await _load_visit(session, visit_id, principal)
    caregiver = await session.get(Caregiver, payload.caregiver_id)
    if caregiver is None:
        raise NotFoundError("Caregiver not found")

    visit = await scheduling_service.assign_caregiver(
        session, principal=principal, visit=visit, caregiver=caregiver
    )
    return schemas.VisitOut.model_validate(visit)


@router.post("/visits/{visit_id}/clock-in", response_model=schemas.EVVStatusOut, status_code=201)
async def clock_in(
    visit_id: uuid.UUID,
    payload: schemas.ClockInRequest,
    principal: Principal = Depends(requires(Role.caregiver, Role.scheduler, Role.owner_admin)),
    session: AsyncSession = Depends(db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> schemas.EVVStatusOut:
    outcome = await idempotency.claim(
        session,
        principal=principal,
        key=idempotency_key,
        endpoint="visits.clock_in",
        payload={"visit_id": str(visit_id), **payload.model_dump(mode="json")},
    )
    if outcome.is_replay:
        return schemas.EVVStatusOut.model_validate(outcome.replayed_body)

    visit = await _load_visit(session, visit_id, principal)
    record = await scheduling_service.clock_in(
        session,
        principal=principal,
        visit=visit,
        timestamp=payload.timestamp,
        capture_method=CaptureMethod(payload.capture_method),
        lat=payload.geo.lat if payload.geo else None,
        lng=payload.geo.lng if payload.geo else None,
        client_local_uuid=payload.client_local_uuid,
    )

    body = _evv_status_out(record)
    assert outcome.record is not None
    await idempotency.complete(
        session, outcome.record, status=201, body=body.model_dump(mode="json")
    )
    return body


@router.post("/visits/{visit_id}/clock-out", response_model=schemas.ClockOutResponse)
async def clock_out(
    visit_id: uuid.UUID,
    payload: schemas.ClockOutRequest,
    principal: Principal = Depends(requires(Role.caregiver, Role.scheduler, Role.owner_admin)),
    session: AsyncSession = Depends(db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> schemas.ClockOutResponse:
    """Clock out, then evaluate compliance and queue EVV transmission.

    Compliance findings are returned but never block the clock-out. Transmission happens
    asynchronously — the record is left `pending` for the transmission worker, so an
    aggregator outage cannot stop a caregiver from finishing their visit.
    """
    outcome = await idempotency.claim(
        session,
        principal=principal,
        key=idempotency_key,
        endpoint="visits.clock_out",
        payload={"visit_id": str(visit_id), **payload.model_dump(mode="json")},
    )
    if outcome.is_replay:
        return schemas.ClockOutResponse.model_validate(outcome.replayed_body)

    visit = await _load_visit(session, visit_id, principal)
    record = await scheduling_service.clock_out(
        session,
        principal=principal,
        visit=visit,
        timestamp=payload.timestamp,
        lat=payload.geo.lat if payload.geo else None,
        lng=payload.geo.lng if payload.geo else None,
        client_local_uuid=payload.client_local_uuid,
    )

    findings = await scheduling_service.evaluate_visit_compliance(
        session, principal=principal, visit=visit
    )

    body = schemas.ClockOutResponse(
        evv=_evv_status_out(record),
        compliance_findings=[
            schemas.ComplianceFindingOut(
                rule_key=f.rule_key,
                severity=f.severity.value,
                message=f.message,
                details=f.details,
            )
            for f in findings
        ],
    )
    assert outcome.record is not None
    await idempotency.complete(
        session, outcome.record, status=200, body=body.model_dump(mode="json")
    )
    return body


@router.get("/visits/{visit_id}/evv-status", response_model=schemas.EVVStatusOut)
async def evv_status(
    visit_id: uuid.UUID,
    principal: Principal = Depends(
        requires(Role.owner_admin, Role.scheduler, Role.caregiver, Role.auditor)
    ),
    session: AsyncSession = Depends(db_session),
) -> schemas.EVVStatusOut:
    visit = await _load_visit(session, visit_id, principal)
    record = (
        await session.execute(select(EVVRecord).where(EVVRecord.scheduled_visit_id == visit.id))
    ).scalar_one_or_none()
    if record is None:
        raise NotFoundError("No EVV record exists for this visit yet")
    return _evv_status_out(record)


@router.get("/visits/{visit_id}/compliance", response_model=list[schemas.ComplianceFindingOut])
async def visit_compliance(
    visit_id: uuid.UUID,
    principal: Principal = Depends(
        requires(Role.owner_admin, Role.scheduler, Role.clinical_supervisor, Role.auditor)
    ),
    session: AsyncSession = Depends(db_session),
) -> list[schemas.ComplianceFindingOut]:
    """Evaluate the visit's compliance rules on demand, without changing it."""
    visit = await _load_visit(session, visit_id, principal)
    context = await scheduling_service.build_visit_rule_context(session, visit=visit)
    findings = rules_engine.evaluate("visit", context)
    return [
        schemas.ComplianceFindingOut(
            rule_key=f.rule_key,
            severity=f.severity.value,
            message=f.message,
            details=f.details,
        )
        for f in findings
    ]


@router.get(
    "/visits/{visit_id}/suggested-caregivers",
    response_model=list[schemas.CaregiverSuggestionOut],
)
async def suggested_caregivers(
    visit_id: uuid.UUID,
    principal: Principal = Depends(requires(Role.owner_admin, Role.scheduler)),
    session: AsyncSession = Depends(db_session),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[schemas.CaregiverSuggestionOut]:
    """AI-ranked caregivers for this visit, with inline reasoning (US-1.4.2, US-1.4.4).

    Only caregivers who would actually pass the assignment gates are returned, so every
    suggestion is safe to offer in one tap.
    """
    visit = await _load_visit(session, visit_id, principal)
    suggestions = await matching.suggest_caregivers(session, visit=visit, limit=limit)

    # Ranking influences who is offered work, so surfacing suggestions is itself auditable.
    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.shift_suggestions_generated,
        entity_type="scheduled_visit",
        entity_id=visit.id,
        after_state={
            "suggested_count": len(suggestions),
            "top_caregiver_id": (str(suggestions[0].caregiver_id) if suggestions else None),
        },
    )
    return [schemas.CaregiverSuggestionOut(**s.as_payload()) for s in suggestions]


@router.get("/compliance-exceptions", response_model=list[schemas.ComplianceExceptionOut])
async def list_compliance_exceptions(
    principal: Principal = Depends(
        requires(Role.owner_admin, Role.scheduler, Role.clinical_supervisor, Role.auditor)
    ),
    session: AsyncSession = Depends(db_session),
    include_resolved: bool = Query(default=False),
    severity: str | None = Query(default=None),
) -> list[schemas.ComplianceExceptionOut]:
    """The exception queue (US-1.4.6).

    Most severe first, then oldest first within a severity — an exception that has sat for a
    week is a worse problem than one raised an hour ago, and newest-first would bury it.
    """
    rows = await exceptions_service.list_exceptions(
        session, include_resolved=include_resolved, severity=severity
    )
    return [schemas.ComplianceExceptionOut.model_validate(r) for r in rows]


@router.get("/compliance-exceptions/summary", response_model=schemas.ExceptionSummaryOut)
async def compliance_exception_summary(
    principal: Principal = Depends(
        requires(Role.owner_admin, Role.scheduler, Role.clinical_supervisor, Role.auditor)
    ),
    session: AsyncSession = Depends(db_session),
) -> schemas.ExceptionSummaryOut:
    summary = await exceptions_service.summarize(session)
    return schemas.ExceptionSummaryOut(
        total_open=summary.total_open, by_severity=summary.by_severity
    )


@router.post(
    "/compliance-exceptions/{exception_id}/resolve",
    response_model=schemas.ComplianceExceptionOut,
)
async def resolve_compliance_exception(
    exception_id: uuid.UUID,
    payload: schemas.ResolveException,
    principal: Principal = Depends(
        requires(Role.owner_admin, Role.scheduler, Role.clinical_supervisor)
    ),
    session: AsyncSession = Depends(db_session),
) -> schemas.ComplianceExceptionOut:
    """Resolve an exception — an audited act by a named person, not a silent dismissal."""
    resolved = await exceptions_service.resolve_exception(
        session, principal=principal, exception_id=exception_id, note=payload.note
    )
    return schemas.ComplianceExceptionOut.model_validate(resolved)
