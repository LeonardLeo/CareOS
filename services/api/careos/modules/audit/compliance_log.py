"""Recording and querying compliance reviews."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core.security import Principal
from careos.modules.audit.compliance_log_models import (
    REVIEW_CADENCE_DAYS,
    ComplianceReview,
    ReviewOutcome,
    ReviewType,
)


@dataclass(slots=True)
class ReviewStatus:
    """Current standing of one review type for one agency."""

    review_type: str
    last_performed_on: date | None
    last_outcome: str | None
    next_due_on: date | None
    is_overdue: bool
    #: True when this review has never been recorded. Distinct from overdue: never-performed
    #: is the more serious state, and a dashboard that conflated them would let a review that
    #: has simply never happened hide behind a comfortable-looking "not yet due".
    never_performed: bool


async def record_review(
    session: AsyncSession,
    *,
    principal: Principal | None,
    agency_id: uuid.UUID,
    review_type: ReviewType,
    outcome: ReviewOutcome,
    performed_by: str,
    performed_on: date | None = None,
    scope: str | None = None,
    model_version: str | None = None,
    summary: str | None = None,
    details: dict[str, Any] | None = None,
) -> ComplianceReview:
    """Record one completed review.

    Prior reviews of the same type are marked superseded rather than deleted — the history of
    what was reviewed and when is the entire point of the table.
    """
    review = ComplianceReview(
        agency_id=agency_id,
        review_type=review_type,
        performed_on=performed_on or datetime.now(UTC).date(),
        outcome=outcome,
        performed_by=performed_by,
        scope=scope,
        model_version=model_version,
        summary=summary,
        details=details or {},
        recorded_by_user_id=principal.user_id if principal else None,
    )
    review.next_due_on = review.compute_next_due()

    existing = (
        (
            await session.execute(
                select(ComplianceReview).where(
                    ComplianceReview.review_type == review_type,
                    ComplianceReview.superseded_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    for prior in existing:
        # Scope-specific reviews (a consent-law review for one state) do not supersede one
        # another, since they cover different ground.
        if prior.scope == scope:
            prior.superseded_at = now

    session.add(review)
    await session.flush()
    return review


async def review_status(session: AsyncSession, *, as_of: date | None = None) -> list[ReviewStatus]:
    """Standing of every review type, including those never performed.

    Enumerates from `ReviewType` rather than from the rows present, so a review that has never
    been run appears as a gap rather than being silently absent.
    """
    today = as_of or datetime.now(UTC).date()
    rows = (
        (
            await session.execute(
                select(ComplianceReview)
                .where(ComplianceReview.superseded_at.is_(None))
                .order_by(ComplianceReview.performed_on.desc())
            )
        )
        .scalars()
        .all()
    )

    latest: dict[ReviewType, ComplianceReview] = {}
    for row in rows:
        latest.setdefault(row.review_type, row)

    statuses: list[ReviewStatus] = []
    for review_type in ReviewType:
        found = latest.get(review_type)
        if found is None:
            statuses.append(
                ReviewStatus(
                    review_type=review_type.value,
                    last_performed_on=None,
                    last_outcome=None,
                    next_due_on=None,
                    # A review on a calendar cadence that has never run is overdue by
                    # definition. An event-triggered one is not — it has no schedule to be
                    # late against.
                    is_overdue=REVIEW_CADENCE_DAYS.get(review_type) is not None,
                    never_performed=True,
                )
            )
            continue

        statuses.append(
            ReviewStatus(
                review_type=review_type.value,
                last_performed_on=found.performed_on,
                last_outcome=found.outcome.value,
                next_due_on=found.next_due_on,
                is_overdue=found.is_overdue(today),
                never_performed=False,
            )
        )
    return statuses
