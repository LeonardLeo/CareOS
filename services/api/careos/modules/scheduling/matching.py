"""Caregiver-to-shift matching and gap-fill suggestions (US-1.4.2, US-1.4.4).

Two rules shape this module.

**A suggestion must be actionable.** A caregiver who would be refused by
`assert_assignable` — uncleared exclusion check, expired credential, terminated — is excluded
from the results entirely rather than ranked low. Showing a scheduler a name they cannot
actually use, during a live gap-fill under time pressure, is worse than showing nothing:
`09_UX_Design_and_User_Flows.md` Flow A has them acting on these in one tap.

**A suggestion must explain itself.** `09_UX...` principle 4 requires every AI suggestion to
show its reasoning inline. Each result carries the factors behind its score and, where
relevant, the constraint that held it back.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core.errors import NotFoundError
from careos.modules.credentialing.models import Caregiver, Credential, EmploymentStatus
from careos.modules.recruiting.ranking import Score, haversine_miles, shift_scorer
from careos.modules.scheduling.models import CarePlan, Client, ScheduledVisit, VisitStatus

#: Weekly hours beyond which assigning another visit risks overtime. A default, not a legal
#: constant: `06_Compliance_and_Regulatory_Requirements.md` Section 5 notes wage-and-hour
#: rules for home-care workers vary by jurisdiction, so this belongs in agency configuration
#: before it is relied on for pay decisions.
DEFAULT_OVERTIME_THRESHOLD_HOURS = 40.0

#: Window used to compute a caregiver's current committed hours.
_HOURS_LOOKBACK_DAYS = 7


@dataclass(slots=True)
class CaregiverSuggestion:
    caregiver_id: uuid.UUID
    caregiver_name: str
    score: float
    factors: list[dict[str, Any]]
    #: Non-blocking cautions — an overtime risk, or an unusually long drive.
    warnings: list[str]

    def as_payload(self) -> dict[str, Any]:
        return {
            "caregiver_id": str(self.caregiver_id),
            "caregiver_name": self.caregiver_name,
            "score": self.score,
            "factors": self.factors,
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class _CaregiverContext:
    caregiver: Caregiver
    has_conflict: bool
    committed_hours: float
    prior_visits_with_client: int
    valid_credentials: set[str]
    distance_miles: float | None


async def _committed_hours(session: AsyncSession, caregiver_id: uuid.UUID, around: Any) -> float:
    """Hours already scheduled in the week surrounding the visit."""
    window_start = around - timedelta(days=_HOURS_LOOKBACK_DAYS)
    window_end = around + timedelta(days=_HOURS_LOOKBACK_DAYS)
    total = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(
                        func.extract(
                            "epoch",
                            ScheduledVisit.scheduled_end - ScheduledVisit.scheduled_start,
                        )
                    ),
                    0,
                )
            ).where(
                ScheduledVisit.caregiver_id == caregiver_id,
                ScheduledVisit.status.notin_([VisitStatus.cancelled, VisitStatus.missed]),
                ScheduledVisit.scheduled_start >= window_start,
                ScheduledVisit.scheduled_start <= window_end,
            )
        )
    ).scalar_one()
    return float(total) / 3600.0


async def _build_context(
    session: AsyncSession,
    *,
    caregiver: Caregiver,
    visit: ScheduledVisit,
    client: Client,
) -> _CaregiverContext:
    conflict = (
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

    prior = (
        await session.execute(
            select(func.count())
            .select_from(ScheduledVisit)
            .join(CarePlan, CarePlan.id == ScheduledVisit.care_plan_id)
            .where(
                ScheduledVisit.caregiver_id == caregiver.id,
                CarePlan.client_id == client.id,
                ScheduledVisit.status == VisitStatus.completed,
            )
        )
    ).scalar_one()

    service_date = visit.scheduled_start.date()
    credentials = (
        (await session.execute(select(Credential).where(Credential.caregiver_id == caregiver.id)))
        .scalars()
        .all()
    )
    valid = {c.credential_type.upper() for c in credentials if c.is_valid_on(service_date)}

    # Distance needs both endpoints geocoded. Either may be missing — a caregiver may not
    # have supplied an address, and a client record may not be geocoded yet — in which case
    # proximity is simply not a factor rather than a zero.
    caregiver_lat, caregiver_lng = caregiver.geo_lat, caregiver.geo_lng
    client_lat, client_lng = client.geo_lat, client.geo_lng
    distance = None
    if (
        caregiver_lat is not None
        and caregiver_lng is not None
        and client_lat is not None
        and client_lng is not None
    ):
        distance = haversine_miles(
            float(caregiver_lat), float(caregiver_lng), float(client_lat), float(client_lng)
        )

    return _CaregiverContext(
        caregiver=caregiver,
        has_conflict=conflict is not None,
        committed_hours=await _committed_hours(session, caregiver.id, visit.scheduled_start),
        prior_visits_with_client=prior,
        valid_credentials=valid,
        distance_miles=distance,
    )


def _build_shift_features(
    context: _CaregiverContext,
    *,
    required_credentials: list[str],
    visit_hours: float,
    overtime_threshold: float,
) -> dict[str, Any]:
    """Assemble allowlisted features for shift matching."""
    features: dict[str, Any] = {}

    if required_credentials:
        matched = sum(1 for c in required_credentials if c.upper() in context.valid_credentials)
        features["certification_match"] = matched / len(required_credentials)

    if context.distance_miles is not None:
        features["geo_proximity_miles"] = context.distance_miles

    features["availability_overlap"] = 0.0 if context.has_conflict else 1.0
    features["continuity_of_care"] = 1.0 if context.prior_visits_with_client > 0 else 0.0

    projected = context.committed_hours + visit_hours
    features["overtime_headroom"] = 1.0 if projected <= overtime_threshold else 0.0
    return features


async def suggest_caregivers(
    session: AsyncSession,
    *,
    visit: ScheduledVisit,
    limit: int = 10,
    overtime_threshold: float = DEFAULT_OVERTIME_THRESHOLD_HOURS,
) -> list[CaregiverSuggestion]:
    """Rank caregivers who could actually take this visit.

    Candidates that would fail a hard compliance gate are omitted rather than ranked, so
    everything returned is safe to offer in one tap.
    """
    from careos.modules.scheduling.service import assert_assignable

    care_plan = await session.get(CarePlan, visit.care_plan_id)
    if care_plan is None:
        raise NotFoundError("Visit references a care plan that does not exist")
    client = await session.get(Client, care_plan.client_id)
    if client is None:
        raise NotFoundError("Care plan references a client that does not exist")

    candidates = (
        (
            await session.execute(
                select(Caregiver).where(
                    Caregiver.employment_status.in_(
                        [EmploymentStatus.active, EmploymentStatus.onboarding]
                    )
                )
            )
        )
        .scalars()
        .all()
    )

    required = [
        task.get("required_credential")
        for task in (care_plan.authorized_tasks or [])
        if isinstance(task, dict) and task.get("required_credential")
    ]
    visit_hours = (visit.scheduled_end - visit.scheduled_start).total_seconds() / 3600.0

    suggestions: list[CaregiverSuggestion] = []
    for caregiver in candidates:
        try:
            # The gate is the authority on who may be assigned. Reusing it here — rather
            # than reimplementing its conditions — is what keeps suggestions and assignment
            # from drifting apart as the rules change.
            await assert_assignable(session, caregiver=caregiver, visit=visit)
        except Exception:  # noqa: BLE001 - any gate failure means "not offerable"
            continue

        context = await _build_context(session, caregiver=caregiver, visit=visit, client=client)
        if context.has_conflict:
            # Double-booking is refused at assignment, so never suggest it.
            continue

        features = _build_shift_features(
            context,
            required_credentials=[c for c in required if c],
            visit_hours=visit_hours,
            overtime_threshold=overtime_threshold,
        )
        score: Score = shift_scorer.score(features)

        warnings: list[str] = []
        if features.get("overtime_headroom") == 0.0:
            projected = context.committed_hours + visit_hours
            warnings.append(
                f"Assigning this visit would put them at ~{projected:.1f}h this week, "
                f"above the {overtime_threshold:.0f}h overtime threshold"
            )
        if context.distance_miles is not None and context.distance_miles > 30:
            warnings.append(
                f"Client is ~{context.distance_miles:.0f} miles away, which may mean "
                "significant unpaid travel time"
            )

        suggestions.append(
            CaregiverSuggestion(
                caregiver_id=caregiver.id,
                caregiver_name=caregiver.legal_name,
                score=score.value,
                factors=score.as_payload(),
                warnings=warnings,
            )
        )

    suggestions.sort(key=lambda s: s.score, reverse=True)
    return suggestions[:limit]


async def detect_gaps(session: AsyncSession, *, within_hours: int = 48) -> list[ScheduledVisit]:
    """Unassigned visits starting soon (US-1.4.4).

    Ordered soonest-first: `09_UX...` principle 3 makes the exception queue a scheduler's
    default view, and the most urgent gap is the one that should be at the top of it.
    """
    from datetime import datetime

    now = datetime.now(UTC)
    horizon = now + timedelta(hours=within_hours)
    return list(
        (
            await session.execute(
                select(ScheduledVisit)
                .where(
                    ScheduledVisit.status == VisitStatus.open,
                    ScheduledVisit.caregiver_id.is_(None),
                    ScheduledVisit.scheduled_start >= now,
                    ScheduledVisit.scheduled_start <= horizon,
                )
                .order_by(ScheduledVisit.scheduled_start)
            )
        )
        .scalars()
        .all()
    )
