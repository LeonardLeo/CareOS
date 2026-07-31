"""EVV transmission worker.

Transmission is deliberately not part of the clock-out request. `07_Integration_Specifications.md`
Section 2 requires retry with backoff and escalation to the agency dashboard, none of which
belongs between a caregiver and finishing their visit. The request path writes a `pending`
record; this worker drains it.

Backoff is exponential on `transmission_attempts`. After `MAX_ATTEMPTS` the record stops
being retried and a compliance exception is raised instead, because at that point it needs a
human — silently retrying forever would leave a visit permanently unbillable with nobody
told.

Currently driven by :func:`run_once` from a scheduled invocation. When queue volume warrants
it this moves behind the durable queue named in `03_Technical_Architecture.md` Section 2; the
per-record logic here does not change.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core import metrics
from careos.core.errors import CareOSError
from careos.db.session import tenant_session
from careos.modules.scheduling import service as scheduling
from careos.modules.scheduling.models import (
    ComplianceException,
    EVVRecord,
    ScheduledVisit,
    TransmissionStatus,
)

logger = structlog.get_logger(__name__)

#: Give up automated retries after this many attempts and escalate to a human.
MAX_ATTEMPTS = 6

#: Base delay; the nth retry waits BASE * 2**(n-1), capped at MAX_BACKOFF.
BASE_BACKOFF = timedelta(minutes=2)
MAX_BACKOFF = timedelta(hours=6)


#: "Due now" sentinel for records that have never been attempted. A fixed point in the past
#: rather than `now()`, because the caller compares against its own `now` captured a moment
#: earlier — returning `now()` here would make a brand-new record test as not-yet-due by a
#: few microseconds and never get picked up.
_ALWAYS_DUE = datetime(1970, 1, 1, tzinfo=UTC)


def next_attempt_due(attempts: int, last_attempt: datetime | None) -> datetime:
    """When a record with `attempts` failures becomes eligible again."""
    if last_attempt is None or attempts <= 0:
        return _ALWAYS_DUE
    delay = min(BASE_BACKOFF * (2 ** (attempts - 1)), MAX_BACKOFF)
    return last_attempt + delay


@dataclass(slots=True)
class TransmissionRun:
    attempted: int = 0
    acknowledged: int = 0
    still_pending: int = 0
    rejected: int = 0
    escalated: int = 0


async def _select_due_records(session: AsyncSession, limit: int) -> list[EVVRecord]:
    """Records that are complete, not yet acknowledged, and past their backoff window."""
    candidates = (
        (
            await session.execute(
                select(EVVRecord)
                .where(
                    EVVRecord.transmission_status.in_(
                        [TransmissionStatus.pending, TransmissionStatus.transmitted]
                    ),
                    EVVRecord.clock_out_time.is_not(None),
                    EVVRecord.transmission_attempts < MAX_ATTEMPTS,
                )
                .order_by(EVVRecord.clock_out_time)
                .limit(limit * 4)
                # SKIP LOCKED so two worker instances never transmit the same visit twice.
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )

    now = datetime.now(UTC)
    due = [
        record
        for record in candidates
        if next_attempt_due(record.transmission_attempts, record.last_transmission_at) <= now
    ]
    return due[:limit]


async def _escalate_exhausted(session: AsyncSession, agency_id: uuid.UUID) -> int:
    """Raise a compliance exception for records that have exhausted their retries."""
    exhausted = (
        (
            await session.execute(
                select(EVVRecord).where(
                    EVVRecord.transmission_attempts >= MAX_ATTEMPTS,
                    EVVRecord.transmission_status.in_(
                        [TransmissionStatus.pending, TransmissionStatus.transmitted]
                    ),
                )
            )
        )
        .scalars()
        .all()
    )

    escalated = 0
    for record in exhausted:
        already_open = (
            await session.execute(
                select(ComplianceException.id).where(
                    ComplianceException.rule_key == "evv.transmission_exhausted",
                    ComplianceException.entity_id == record.scheduled_visit_id,
                    ComplianceException.resolved_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if already_open is not None:
            continue

        session.add(
            ComplianceException(
                agency_id=agency_id,
                rule_key="evv.transmission_exhausted",
                severity="critical",
                entity_type="visit",
                entity_id=record.scheduled_visit_id,
                message=(
                    f"EVV transmission failed {record.transmission_attempts} times and will "
                    "not be retried automatically. This visit is not compliant until it is "
                    "transmitted and acknowledged."
                ),
                details={
                    "evv_record_id": str(record.id),
                    "aggregator": record.aggregator_key,
                    "last_response": record.aggregator_response_payload,
                },
            )
        )
        escalated += 1
    await session.flush()
    return escalated


async def run_once(agency_id: uuid.UUID, *, limit: int = 50) -> TransmissionRun:
    """Drain up to `limit` due EVV records for one agency.

    Scoped per agency because the session's tenant context drives RLS. The scheduler that
    invokes this iterates active agencies.
    """
    run = TransmissionRun()

    async with tenant_session(agency_id) as session:
        due = await _select_due_records(session, limit)

        for record in due:
            visit = await session.get(ScheduledVisit, record.scheduled_visit_id)
            if visit is None:
                continue
            run.attempted += 1
            try:
                await scheduling.transmit_evv_record(
                    session, principal=None, visit=visit, record=record
                )
            except CareOSError as exc:
                # A configuration problem (no adapter for the state, unvalidated sandbox)
                # is not retryable by waiting. Count the attempt so it escalates to a human
                # rather than spinning.
                record.transmission_attempts += 1
                record.last_transmission_at = datetime.now(UTC)
                metrics.evv_transmissions_total.labels(outcome="configuration_error").inc()
                logger.warning(
                    "evv.transmission_configuration_error",
                    evv_record_id=str(record.id),
                    error=exc.message,
                    code=exc.code,
                )
                continue

            if record.transmission_status is TransmissionStatus.acknowledged:
                run.acknowledged += 1
                metrics.evv_transmissions_total.labels(outcome="acknowledged").inc()
            elif record.transmission_status is TransmissionStatus.rejected:
                run.rejected += 1
                metrics.evv_transmissions_total.labels(outcome="rejected").inc()
            else:
                run.still_pending += 1
                metrics.evv_transmissions_total.labels(outcome="pending").inc()

        run.escalated = await _escalate_exhausted(session, agency_id)
        # Escalation means a record has exhausted its retries and now needs a person. Counted
        # separately from a rejection because the two need different humans: a rejection is a
        # data problem for the agency, an escalation is an unattended compliance liability.
        if run.escalated:
            metrics.evv_escalations_total.inc(run.escalated)

    logger.info(
        "evv.transmission_run",
        agency_id=str(agency_id),
        attempted=run.attempted,
        acknowledged=run.acknowledged,
        rejected=run.rejected,
        still_pending=run.still_pending,
        escalated=run.escalated,
    )
    return run
