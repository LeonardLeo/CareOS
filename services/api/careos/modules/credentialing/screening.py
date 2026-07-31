"""Ordering background checks and applying their verdicts.

`assert_assignable` refuses a caregiver for publicly-funded work unless
`exclusion_check_status` is `cleared`. Until now the only thing that could set it was an
administrator calling `POST /caregivers/{id}/exclusion-check` after looking a caregiver up on
the OIG and GSA websites by hand. That is workable for twenty caregivers and not workable at
all beyond it, and it is why `13_Phase_1_Launch_Plan.md` moves this ahead of most of the
list.

Three properties this module exists to hold:

**A screening is not a moment, it is a lifecycle.** Ordered, outstanding for hours or days,
then resolved. `ScreeningRequest` carries that; nothing here pretends a verdict is available
at order time.

**Clearing is a positive act.** Nothing in this module writes `cleared` except a vendor
verdict of `clear` for an exclusion-list check. An unreachable vendor, an unparseable
response, a request that never resolves — every one of those leaves the caregiver where they
were, which for a new hire is `not_run` and therefore unassignable. That asymmetry is
deliberate and is the whole reason the adapter raises instead of defaulting.

**A flag on someone already working is a scheduling emergency, not a record update.** A
re-screen that comes back flagged for a caregiver holding future visits raises a compliance
exception. It does not silently unassign them: pulling a caregiver off five visits without
telling anyone leaves five clients with nobody arriving and no queue entry explaining why.
The exception is what puts it in front of a scheduler.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.config import get_settings
from careos.core.audit import AuditAction, record_audit
from careos.core.crypto import decrypt_field
from careos.core.errors import ConflictError, NotFoundError, ScreeningUnavailableError
from careos.core.security import Principal
from careos.integrations.screening.base import (
    DEFAULT_ONBOARDING_CHECKS,
    ScreeningAdapter,
    ScreeningCheck,
    ScreeningError,
    ScreeningResult,
    ScreeningSubject,
    ScreeningVerdict,
)
from careos.integrations.screening.registry import get_screening_adapter
from careos.modules.credentialing.models import (
    Caregiver,
    ExclusionCheckStatus,
    ScreeningRequest,
)

logger = structlog.get_logger(__name__)

#: Lifecycle values for `screening_request.status`. Distinct from the verdict: a request can
#: be `completed` with a verdict of `flagged`, and `failed` carries no verdict at all.
STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

#: Rule key for the exception raised when a working caregiver is flagged. Matches the
#: `<domain>.<condition>` shape the EVV rules use, so the exceptions queue reads uniformly.
FLAGGED_WHILE_SCHEDULED_RULE = "screening.flagged_with_future_visits"


@dataclass(slots=True)
class ScreeningRun:
    """What one worker pass did, for logging and for tests to assert against."""

    considered: int = 0
    ordered: int = 0
    resolved: int = 0
    failed: int = 0
    #: Caregiver ids newly flagged in this pass. Named rather than counted because a single
    #: one is worth reading in a log line.
    flagged: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------------------


def _subject_for(caregiver: Caregiver) -> ScreeningSubject:
    """The identity a vendor search needs, and nothing else.

    Date of birth is decrypted here because a search cannot be run without it, and is passed
    as a string rather than the encrypted column so no adapter can accidentally persist
    ciphertext it cannot read. The full SSN is never assembled — most exclusion-list matching
    does not need it, and a field this module never holds is one no adapter can leak.
    """
    return ScreeningSubject(
        caregiver_id=caregiver.id,
        legal_name=caregiver.legal_name,
        date_of_birth=decrypt_field(caregiver.dob_encrypted),
        state_code=None,
    )


async def _outstanding_request(
    session: AsyncSession, caregiver_id: uuid.UUID
) -> ScreeningRequest | None:
    return (
        await session.execute(
            select(ScreeningRequest)
            .where(
                ScreeningRequest.caregiver_id == caregiver_id,
                ScreeningRequest.status == STATUS_PENDING,
            )
            .order_by(ScreeningRequest.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def order_screening(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    caregiver_id: uuid.UUID,
    checks: tuple[ScreeningCheck, ...] = DEFAULT_ONBOARDING_CHECKS,
    principal: Principal | None = None,
    adapter: ScreeningAdapter | None = None,
) -> ScreeningRequest:
    """Submit a search to the configured vendor and record it as outstanding.

    Refuses to order a second search while one is outstanding. These are billed per search
    and they touch a real person's records, so a double-click on an admin screen must not
    produce two of them.

    `principal` is None when the re-screening job orders one. The audit row is still written,
    with a null actor — the same shape a failed login uses. A recurring screening with no
    audit trail would be indistinguishable from one that never ran.
    """
    caregiver = await session.get(Caregiver, caregiver_id)
    if caregiver is None:
        raise NotFoundError("Caregiver not found")

    existing = await _outstanding_request(session, caregiver_id)
    if existing is not None:
        raise ConflictError(
            "A screening is already outstanding for this caregiver",
            details={
                "screening_request_id": str(existing.id),
                "ordered_at": existing.created_at.isoformat(),
            },
        )

    adapter = adapter or get_screening_adapter()
    try:
        order = await adapter.order(_subject_for(caregiver), checks)
    except ScreeningError as exc:
        # Recorded as a failed request rather than discarded. An agency that cannot get
        # anyone screened needs to see attempts, and a vendor outage is invisible if the
        # only trace of it is an exception in a log.
        session.add(
            ScreeningRequest(
                agency_id=agency_id,
                caregiver_id=caregiver_id,
                vendor_key=adapter.adapter_key,
                check_types=[c.value for c in checks],
                status=STATUS_FAILED,
                result_payload={"error": str(exc)},
            )
        )
        await session.flush()
        raise ScreeningUnavailableError(
            "The screening vendor did not accept the request",
            details={"vendor": adapter.adapter_key, "reason": str(exc)},
        ) from exc

    request = ScreeningRequest(
        agency_id=agency_id,
        caregiver_id=caregiver_id,
        vendor_key=adapter.adapter_key,
        check_types=[c.value for c in order.checks],
        vendor_request_id=order.vendor_request_id,
        status=STATUS_PENDING,
        result_payload={},
    )
    session.add(request)
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=agency_id,
        action=AuditAction.screening_ordered,
        entity_type="caregiver",
        entity_id=caregiver_id,
        after_state={
            "screening_request_id": str(request.id),
            "vendor_key": adapter.adapter_key,
            "checks": [c.value for c in order.checks],
            # The vendor's id, not the subject's data. What was disclosed is described by
            # the check types; repeating the identity here would put it in a second table.
            "vendor_request_id": order.vendor_request_id,
        },
    )
    return request


# --------------------------------------------------------------------------------------
# Applying a verdict
# --------------------------------------------------------------------------------------


def _exclusion_status_for(result: ScreeningResult) -> ExclusionCheckStatus | None:
    """Map a vendor verdict onto the gate `assert_assignable` reads.

    None means "change nothing", which is different from `not_run`: a caregiver cleared last
    month who is mid-re-screen must keep working rather than being benched because a poll came
    back "still looking".

    In practice `record_result` returns before calling this for a pending result, so the
    pending branch here is a second line rather than the one doing the work. It is kept, and
    tested directly, because the alternative — a mapping function whose only unhandled case
    is the one that would clear somebody — is the shape of the bug this module is built
    around.
    """
    if result.verdict is ScreeningVerdict.clear:
        return ExclusionCheckStatus.cleared
    if result.verdict is ScreeningVerdict.flagged:
        return ExclusionCheckStatus.flagged
    return None


async def _future_assigned_visit_count(session: AsyncSession, caregiver_id: uuid.UUID) -> int:
    """How many visits this caregiver is still expected to work.

    Imported locally: `scheduling.service` imports this package's models, so a module-level
    import here would close the cycle.
    """
    from sqlalchemy import func

    from careos.modules.scheduling.models import ScheduledVisit, VisitStatus

    return (
        await session.execute(
            select(func.count())
            .select_from(ScheduledVisit)
            .where(
                ScheduledVisit.caregiver_id == caregiver_id,
                ScheduledVisit.scheduled_start >= datetime.now(UTC),
                # `open` is deliberately absent: an unassigned visit is not this caregiver's
                # to lose. Cancelled and completed ones are not future work either.
                ScheduledVisit.status.in_(
                    [VisitStatus.assigned, VisitStatus.confirmed, VisitStatus.in_progress]
                ),
            )
        )
    ).scalar_one()


async def _raise_flagged_exception(
    session: AsyncSession, *, caregiver: Caregiver, visit_count: int, result: ScreeningResult
) -> None:
    """Put a flagged, still-scheduled caregiver in front of a human.

    Deliberately does not unassign the visits. An excluded caregiver must not work a
    Medicaid-billed visit, but silently emptying five slots produces five clients with nobody
    arriving and no record of why. `assert_assignable` already blocks any *new* assignment
    the moment the status flips; this makes the existing ones somebody's problem today.
    """
    from careos.modules.scheduling.models import ComplianceException

    open_exception = (
        await session.execute(
            select(ComplianceException).where(
                ComplianceException.rule_key == FLAGGED_WHILE_SCHEDULED_RULE,
                ComplianceException.entity_type == "caregiver",
                ComplianceException.entity_id == caregiver.id,
                ComplianceException.resolved_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    details = {
        "future_visits_assigned": visit_count,
        "vendor_request_id": result.vendor_request_id,
        "per_check": result.per_check,
        "match_count": len(result.matches),
        "remediation": (
            "Reassign the caregiver's future visits, then adjudicate the match. New "
            "assignments are already blocked by the exclusion gate (PRD US-1.3.2)."
        ),
    }
    message = (
        f"{caregiver.legal_name} was flagged by an exclusion screening and still has "
        f"{visit_count} future visit(s) assigned"
    )

    if open_exception is not None:
        # Re-flagged before anyone resolved the first one. Update rather than duplicate, so
        # the queue shows one problem with a current visit count.
        open_exception.message = message
        open_exception.details = details
        return

    session.add(
        ComplianceException(
            agency_id=caregiver.agency_id,
            rule_key=FLAGGED_WHILE_SCHEDULED_RULE,
            severity="critical",
            entity_type="caregiver",
            entity_id=caregiver.id,
            message=message,
            details=details,
        )
    )


async def record_result(
    session: AsyncSession,
    *,
    request: ScreeningRequest,
    result: ScreeningResult,
    principal: Principal | None = None,
) -> ExclusionCheckStatus | None:
    """Apply a vendor verdict. Returns the caregiver's new status, or None if unchanged.

    Safe to call twice with the same final result: the second call finds the request already
    completed and does nothing. Vendors retry callbacks, and a duplicate delivery must not
    produce a second webhook or a second audit row.
    """
    if request.status == STATUS_COMPLETED:
        return None
    if not result.is_final:
        return None

    caregiver = await session.get(Caregiver, request.caregiver_id)
    if caregiver is None:
        raise NotFoundError("Screening result refers to a caregiver that no longer exists")

    was = caregiver.exclusion_check_status
    request.status = STATUS_COMPLETED
    request.completed_at = result.completed_at
    request.result_payload = {
        "verdict": result.verdict.value,
        "per_check": result.per_check,
        "matches": result.matches,
    }

    new_status = _exclusion_status_for(result)
    if new_status is not None:
        caregiver.exclusion_check_status = new_status
        caregiver.exclusion_checked_at = result.completed_at

    if new_status is ExclusionCheckStatus.flagged:
        visit_count = await _future_assigned_visit_count(session, caregiver.id)
        if visit_count:
            await _raise_flagged_exception(
                session, caregiver=caregiver, visit_count=visit_count, result=result
            )

    await session.flush()

    if principal is not None:
        await record_audit(
            session,
            principal=principal,
            agency_id=request.agency_id,
            action=AuditAction.screening_completed,
            entity_type="caregiver",
            entity_id=caregiver.id,
            before_state={"exclusion_check_status": was.value},
            after_state={
                "exclusion_check_status": caregiver.exclusion_check_status.value,
                "verdict": result.verdict.value,
                "vendor_key": request.vendor_key,
                "screening_request_id": str(request.id),
            },
        )

    await _announce(session, request=request, caregiver=caregiver, result=result)
    return new_status


async def _announce(
    session: AsyncSession,
    *,
    request: ScreeningRequest,
    caregiver: Caregiver,
    result: ScreeningResult,
) -> None:
    """Queue `background_check.completed`, which had no producer until now.

    Payload is identifiers and a verdict. Deliberately not the match detail: a receiver is a
    third-party system under a subscription, and the specifics of why someone was flagged are
    for the agency's adjudication screen, not for a webhook body.
    """
    from careos.modules.webhooks import service as webhook_service
    from careos.modules.webhooks.models import WebhookEvent

    await webhook_service.enqueue(
        session,
        agency_id=request.agency_id,
        event=WebhookEvent.background_check_completed,
        payload={
            "caregiver_id": str(caregiver.id),
            "screening_request_id": str(request.id),
            "verdict": result.verdict.value,
            "check_types": list(request.check_types),
            "completed_at": (result.completed_at.isoformat() if result.completed_at else None),
            "exclusion_check_status": caregiver.exclusion_check_status.value,
        },
        dedupe_on={"screening_request_id": str(request.id)},
    )


# --------------------------------------------------------------------------------------
# Worker jobs
# --------------------------------------------------------------------------------------


async def poll_outstanding(agency_id: uuid.UUID) -> ScreeningRun:
    """Fetch verdicts for one agency's outstanding requests.

    Polling rather than relying only on callbacks. A vendor callback that is dropped, or
    delivered to a URL that was rotated, leaves a caregiver permanently unassignable with no
    signal — and "the webhook never arrived" is not something an agency can diagnose. The
    poll is the floor under the callback, not a replacement for it.
    """
    from careos.db.session import tenant_session

    run = ScreeningRun()
    adapter = get_screening_adapter()

    async with tenant_session(agency_id) as session:
        outstanding = (
            (
                await session.execute(
                    select(ScreeningRequest).where(ScreeningRequest.status == STATUS_PENDING)
                )
            )
            .scalars()
            .all()
        )
        for request in outstanding:
            run.considered += 1
            if request.vendor_request_id is None:
                continue
            try:
                result = await adapter.fetch(request.vendor_request_id)
            except ScreeningError as exc:
                run.failed += 1
                logger.warning(
                    "screening.fetch_failed",
                    agency_id=str(agency_id),
                    screening_request_id=str(request.id),
                    error=str(exc),
                )
                continue
            status = await record_result(session, request=request, result=result)
            if status is not None:
                run.resolved += 1
            if status is ExclusionCheckStatus.flagged:
                run.flagged.append(str(request.caregiver_id))

    if run.resolved or run.flagged:
        logger.info(
            "screening.polled",
            agency_id=str(agency_id),
            resolved=run.resolved,
            flagged=run.flagged,
        )
    return run


async def order_due_rescreens(agency_id: uuid.UUID, *, now: datetime | None = None) -> ScreeningRun:
    """Re-order exclusion screening for caregivers whose last check has gone stale.

    `07_Integration_Specifications.md` Section 3 expects recurring re-verification, and
    `exclusion_checked_at` exists for exactly this. OIG republishes LEIE monthly, so a
    caregiver cleared six months ago is carrying a claim about a list that has been replaced
    five times since.

    Only the exclusion-list check is re-ordered. Re-running a full criminal-history bundle
    monthly on every caregiver would be expensive and is not what the recurring obligation
    asks for.
    """
    from careos.db.session import tenant_session

    settings = get_settings()
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.screening_recheck_interval_days)

    run = ScreeningRun()
    async with tenant_session(agency_id) as session:
        due = (
            (
                await session.execute(
                    select(Caregiver).where(
                        Caregiver.exclusion_check_status == ExclusionCheckStatus.cleared,
                        Caregiver.exclusion_checked_at < cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        for caregiver in due:
            run.considered += 1
            if await _outstanding_request(session, caregiver.id) is not None:
                continue
            try:
                await order_screening(
                    session,
                    agency_id=agency_id,
                    caregiver_id=caregiver.id,
                    checks=(ScreeningCheck.exclusion_list,),
                )
            except ScreeningUnavailableError:
                run.failed += 1
                continue
            run.ordered += 1

    if run.ordered or run.failed:
        logger.info(
            "screening.rescreens_ordered",
            agency_id=str(agency_id),
            ordered=run.ordered,
            failed=run.failed,
            considered=run.considered,
        )
    return run
