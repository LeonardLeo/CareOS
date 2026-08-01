"""Reconciling visits delivered against visits the aggregator has acknowledged.

The transmission worker retries a record that fails to send and escalates one that exhausts
its retries. Neither of those covers the case that actually costs an agency money, because
neither of them is a failure: a visit that was delivered, clocked in and out, and for which
nothing was ever queued; a record submitted and accepted at the door and never acknowledged;
a rejection nobody read. Each of those looks exactly like a healthy system from the inside.
`13_Phase_1_Launch_Plan.md` 5.1 calls this out — a silently rejected batch is invisible until
a payer says so, and by then the visits are delivered and the caregivers are paid.

So this compares the two sides that should agree and reports where they do not:

* **Visits that happened, with nothing queued.** A completed or in-progress visit with no
  `evv_record` at all. The most dangerous of the four, because every retry, alert, and
  escalation in the system is keyed on a record that does not exist.
* **Submitted and never acknowledged.** `07_Integration_Specifications.md` Section 2 is
  explicit that a visit is not compliant until acknowledged, not merely submitted, so a
  record parked in `transmitted` is an unbilled visit wearing a green light.
* **Queued and never sent.** Still `pending` long after the visit ended, which means the
  worker never reached it — a stuck queue rather than a rejected record.
* **Rejected and unattended.** The aggregator said no and nobody has resolved it.

What this deliberately does *not* do yet is query the aggregator for its own count. Every
state has a different interface for that, and inventing one before the New York sandbox run
would be guessing at a shape. The comparison here is between what we recorded and what we
believe we sent, which is the half that is knowable today; `AggregatorTally` is where the
other half attaches.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.modules.scheduling.models import (
    ComplianceException,
    EVVRecord,
    ScheduledVisit,
    TransmissionStatus,
    VisitStatus,
)

logger = structlog.get_logger(__name__)

#: Rule keys, in the `<domain>.<condition>` shape the EVV rules already use so the exceptions
#: queue reads uniformly. Stable strings: an agency's saved filters and an auditor's report
#: both key on these, so renaming one is a migration rather than an edit.
RULE_NO_RECORD = "evv.visit_delivered_without_record"
RULE_UNACKNOWLEDGED = "evv.submitted_without_acknowledgement"
RULE_NEVER_SENT = "evv.queued_without_transmission"
RULE_REJECTED_UNRESOLVED = "evv.rejected_and_unresolved"

#: How long after a visit ends before its silence counts as a divergence rather than as work
#: in progress. Generous on purpose: the transmission worker retries with exponential backoff
#: up to six hours, so anything tighter would report the backoff itself as a problem.
DEFAULT_GRACE = timedelta(hours=24)

#: Visits older than this are not re-reported. A divergence from six months ago is a billing
#: dispute, not an operational alert, and a queue that accumulates them stops being read.
DEFAULT_LOOKBACK = timedelta(days=30)

#: Visit states that mean care was actually delivered. `open` and `cancelled` are excluded:
#: no visit happened, so no EVV record is owed.
DELIVERED_STATUSES = (VisitStatus.completed, VisitStatus.in_progress)


@dataclass(frozen=True, slots=True)
class AggregatorTally:
    """What the aggregator says it holds for a window.

    Unused until a state's interface for asking is known. It exists as a named shape so the
    place it plugs into is decided now, while the reconciliation logic is being written,
    rather than being retrofitted around whatever the first vendor happens to return.
    """

    state_code: str
    window_start: datetime
    window_end: datetime
    acknowledged_count: int


@dataclass(slots=True)
class Divergence:
    """One visit on which the two sides disagree."""

    rule_key: str
    visit_id: uuid.UUID
    message: str
    details: dict[str, object]


@dataclass(slots=True)
class ReconciliationRun:
    """What one pass found, and what it did about it."""

    visits_examined: int = 0
    divergences: list[Divergence] = field(default_factory=list)
    #: Exceptions newly opened. Lower than `len(divergences)` when one was already open.
    raised: int = 0
    #: Exceptions closed because the divergence they described has resolved itself.
    resolved: int = 0

    @property
    def is_clean(self) -> bool:
        return not self.divergences

    def by_rule(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for divergence in self.divergences:
            counts[divergence.rule_key] = counts.get(divergence.rule_key, 0) + 1
        return counts


async def find_divergences(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    grace: timedelta = DEFAULT_GRACE,
    lookback: timedelta = DEFAULT_LOOKBACK,
) -> tuple[list[Divergence], int]:
    """Compare delivered visits against their EVV records. Returns (divergences, examined).

    Read-only, so it can be run against production to answer "are we actually compliant?"
    without writing anything. `reconcile` is the half that acts on the answer.
    """
    now = now or datetime.now(UTC)
    cutoff_recent = now - grace
    cutoff_old = now - lookback

    rows = (
        await session.execute(
            select(ScheduledVisit, EVVRecord)
            .outerjoin(EVVRecord, EVVRecord.scheduled_visit_id == ScheduledVisit.id)
            .where(
                ScheduledVisit.status.in_(DELIVERED_STATUSES),
                ScheduledVisit.scheduled_end < cutoff_recent,
                ScheduledVisit.scheduled_end >= cutoff_old,
            )
            .order_by(ScheduledVisit.scheduled_end)
        )
    ).all()

    divergences: list[Divergence] = []
    for visit, record in rows:
        divergence = _classify(visit, record)
        if divergence is not None:
            divergences.append(divergence)

    return divergences, len(rows)


def _classify(visit: ScheduledVisit, record: EVVRecord | None) -> Divergence | None:
    """Which of the four divergences this visit shows, if any.

    Ordered by severity of consequence rather than by likelihood. A visit with no record at
    all is checked first because every other mechanism in the system — retries, escalation,
    the alert on transmission staleness — is keyed on a record, so its absence is the one
    failure nothing else can see.
    """
    common = {
        "scheduled_end": visit.scheduled_end.isoformat(),
        "service_state": visit.service_state,
        "payer_type": visit.payer_type,
    }

    if record is None:
        return Divergence(
            rule_key=RULE_NO_RECORD,
            visit_id=visit.id,
            message=(
                "This visit was delivered and no EVV record was ever created for it. "
                "Nothing has been transmitted and nothing will retry."
            ),
            details={
                **common,
                "visit_status": visit.status.value,
                "remediation": (
                    "Recreate the EVV record from the clock-in and clock-out times on file, "
                    "or record a manual-entry exception with a documented reason."
                ),
            },
        )

    detail = {
        **common,
        "evv_record_id": str(record.id),
        "transmission_status": record.transmission_status.value,
        "transmission_attempts": record.transmission_attempts,
        "aggregator": record.aggregator_key,
        "last_transmission_at": (
            record.last_transmission_at.isoformat() if record.last_transmission_at else None
        ),
    }

    if record.transmission_status is TransmissionStatus.transmitted:
        return Divergence(
            rule_key=RULE_UNACKNOWLEDGED,
            visit_id=visit.id,
            message=(
                "This visit was submitted to the aggregator and has not been acknowledged. "
                "A visit is not compliant until it is acknowledged, not merely submitted."
            ),
            details={
                **detail,
                "remediation": (
                    "Check the aggregator portal for this reference. An accepted submission "
                    "that never acknowledges is usually a batch the aggregator rejected "
                    "downstream without telling us."
                ),
            },
        )

    if record.transmission_status is TransmissionStatus.pending:
        return Divergence(
            rule_key=RULE_NEVER_SENT,
            visit_id=visit.id,
            message=(
                "This visit's EVV record has been queued since the visit ended and has "
                "never been transmitted."
            ),
            details={
                **detail,
                "remediation": (
                    "The transmission worker has not reached this record. Check that the "
                    "worker is running and that this state has a configured, "
                    "sandbox-validated adapter."
                ),
            },
        )

    if record.transmission_status is TransmissionStatus.rejected:
        return Divergence(
            rule_key=RULE_REJECTED_UNRESOLVED,
            visit_id=visit.id,
            message="The aggregator rejected this visit and the rejection has not been resolved.",
            details={
                **detail,
                "aggregator_response": record.aggregator_response_payload,
                "remediation": (
                    "Correct the underlying visit data and re-transmit. A rejection left "
                    "unresolved is an unbillable visit."
                ),
            },
        )

    return None


async def reconcile(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    now: datetime | None = None,
    grace: timedelta = DEFAULT_GRACE,
    lookback: timedelta = DEFAULT_LOOKBACK,
) -> ReconciliationRun:
    """Find divergences and keep the exception queue in step with them.

    Both directions. Opening an exception when a divergence appears is the obvious half; the
    half that decides whether anyone keeps reading the queue is closing one when the
    divergence goes away. A retransmission that succeeds tomorrow should clear today's
    exception without a human dismissing it, or the queue fills with resolved problems and
    the real ones stop standing out.
    """
    run = ReconciliationRun()
    divergences, examined = await find_divergences(session, now=now, grace=grace, lookback=lookback)
    run.visits_examined = examined
    run.divergences = divergences

    open_exceptions = (
        (
            await session.execute(
                select(ComplianceException).where(
                    ComplianceException.rule_key.in_(
                        [
                            RULE_NO_RECORD,
                            RULE_UNACKNOWLEDGED,
                            RULE_NEVER_SENT,
                            RULE_REJECTED_UNRESOLVED,
                        ]
                    ),
                    ComplianceException.entity_type == "visit",
                    ComplianceException.resolved_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    open_by_key = {(e.rule_key, e.entity_id): e for e in open_exceptions}
    current_keys = {(d.rule_key, d.visit_id) for d in divergences}

    stamp = now or datetime.now(UTC)
    for existing in open_exceptions:
        if (existing.rule_key, existing.entity_id) not in current_keys:
            existing.resolved_at = stamp
            run.resolved += 1

    for divergence in divergences:
        already_open = open_by_key.get((divergence.rule_key, divergence.visit_id))
        if already_open is not None:
            # Refresh rather than duplicate: attempt counts and aggregator responses move
            # while the underlying problem stays the same one.
            already_open.message = divergence.message
            already_open.details = dict(divergence.details)
            continue

        session.add(
            ComplianceException(
                agency_id=agency_id,
                rule_key=divergence.rule_key,
                # Critical without exception. Every one of these is a delivered visit that
                # cannot currently be billed and, for a Medicaid client, a compliance finding
                # waiting to be made by somebody else.
                severity="critical",
                entity_type="visit",
                entity_id=divergence.visit_id,
                message=divergence.message,
                details=dict(divergence.details),
            )
        )
        run.raised += 1

    await session.flush()
    return run


async def acknowledged_count(
    session: AsyncSession, *, window_start: datetime, window_end: datetime
) -> int:
    """How many visits we believe the aggregator has acknowledged in a window.

    The number to compare against `AggregatorTally.acknowledged_count` once a state's
    interface for asking is known. Kept here rather than in the caller so that both sides of
    that comparison are defined in the same place and cannot drift into meaning different
    things.
    """
    return (
        await session.execute(
            select(func.count())
            .select_from(EVVRecord)
            .join(ScheduledVisit, ScheduledVisit.id == EVVRecord.scheduled_visit_id)
            .where(
                EVVRecord.transmission_status == TransmissionStatus.acknowledged,
                ScheduledVisit.scheduled_end >= window_start,
                ScheduledVisit.scheduled_end < window_end,
            )
        )
    ).scalar_one()
