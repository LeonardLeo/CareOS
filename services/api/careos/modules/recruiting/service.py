"""Recruiting domain logic — Epic 1.2 and the hire conversion in Epic 1.3."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core.audit import AuditAction, record_audit
from careos.core.errors import ConflictError, NotFoundError
from careos.core.security import Principal
from careos.modules.agency.models import Agency
from careos.modules.credentialing.models import Caregiver, EmploymentStatus, ExclusionCheckStatus
from careos.modules.recruiting.models import ApplicantProfile, JobPosting, PipelineStage
from careos.modules.recruiting.ranking import applicant_scorer, haversine_miles
from careos.modules.scheduling.models import Client, ScheduledVisit, VisitStatus

#: Stage transitions the pipeline permits. A rejected applicant is not silently revived, and
#: a hired one is terminal — reversing either should create a new record with its own audit
#: trail rather than quietly rewriting history on a hiring decision.
ALLOWED_TRANSITIONS: dict[PipelineStage, frozenset[PipelineStage]] = {
    PipelineStage.applied: frozenset({PipelineStage.screened, PipelineStage.rejected}),
    PipelineStage.screened: frozenset({PipelineStage.offer, PipelineStage.rejected}),
    PipelineStage.offer: frozenset({PipelineStage.hired, PipelineStage.rejected}),
    PipelineStage.hired: frozenset(),
    PipelineStage.rejected: frozenset(),
}


@dataclass(slots=True)
class FunnelStage:
    stage: str
    count: int
    #: Conversion from the immediately preceding stage, not from the top of the funnel.
    conversion_from_previous: float | None


async def create_job_posting(
    session: AsyncSession,
    *,
    principal: Principal,
    title: str,
    description: str | None,
    required_credential_types: list[str],
    service_state: str | None,
) -> JobPosting:
    posting = JobPosting(
        agency_id=principal.agency_id,
        title=title,
        description=description,
        required_credential_types=required_credential_types,
        service_state=service_state.upper() if service_state else None,
    )
    session.add(posting)
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.job_posting_created,
        entity_type="job_posting",
        entity_id=posting.id,
        after_state={"title": title, "service_state": posting.service_state},
    )
    return posting


async def ingest_applicant(
    session: AsyncSession,
    *,
    principal: Principal,
    job_posting_id: uuid.UUID | None,
    source: str,
    full_name: str,
    email: str | None,
    phone: str | None,
    claimed_credentials: list[str],
    availability: dict[str, Any],
    geo_lat: float | None,
    geo_lng: float | None,
) -> ApplicantProfile:
    """Record an applicant, normalized regardless of which board they came from.

    `07_Integration_Specifications.md` Section 4 requires inbound applicant data from any job
    board to land in this one shape, so ranking and reporting never learn a vendor's schema.
    """
    if job_posting_id is not None and await session.get(JobPosting, job_posting_id) is None:
        raise NotFoundError("Job posting not found")

    applicant = ApplicantProfile(
        agency_id=principal.agency_id,
        job_posting_id=job_posting_id,
        source=source,
        full_name=full_name,
        email=email,
        phone=phone,
        claimed_credentials=claimed_credentials,
        availability=availability,
        geo_lat=geo_lat,
        geo_lng=geo_lng,
        pipeline_stage=PipelineStage.applied,
        stage_changed_at=datetime.now(UTC),
    )
    session.add(applicant)
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.applicant_ingested,
        entity_type="applicant_profile",
        entity_id=applicant.id,
        after_state={
            "source": source,
            "job_posting_id": str(job_posting_id) if job_posting_id else None,
        },
    )
    return applicant


async def _open_shift_context(
    session: AsyncSession, posting: JobPosting | None
) -> tuple[list[tuple[float, float]], int]:
    """Locations of currently unfilled visits, and how many there are.

    Applicant ranking is relative to the work actually needing staffing (US-1.2.2), so this
    reads the open shifts rather than scoring candidates in the abstract.
    """
    query = (
        select(Client.geo_lat, Client.geo_lng)
        .join(ScheduledVisit, ScheduledVisit.care_plan_id.isnot(None))
        .where(ScheduledVisit.status == VisitStatus.open)
    )
    if posting is not None and posting.service_state:
        query = query.where(Client.service_state == posting.service_state)

    rows = (await session.execute(query)).all()
    locations = [
        (float(lat), float(lng)) for lat, lng in rows if lat is not None and lng is not None
    ]
    return locations, len(rows)


def build_applicant_features(
    applicant: ApplicantProfile,
    *,
    required_credentials: list[str],
    open_shift_locations: list[tuple[float, float]],
    open_shift_count: int,
) -> dict[str, Any]:
    """Assemble the allowlisted feature dict for one applicant.

    Only operational signals are read. Name, address, and date of birth are on the record and
    are deliberately not touched — the scorer would reject them anyway
    (`careos.modules.recruiting.features`).
    """
    features: dict[str, Any] = {}

    if required_credentials:
        claimed = {c.upper() for c in applicant.claimed_credentials}
        matched = sum(1 for c in required_credentials if c.upper() in claimed)
        features["certification_match"] = matched / len(required_credentials)

    if applicant.geo_lat is not None and applicant.geo_lng is not None and open_shift_locations:
        distances = [
            haversine_miles(float(applicant.geo_lat), float(applicant.geo_lng), lat, lng)
            for lat, lng in open_shift_locations
        ]
        # Nearest open shift, not the average: a caregiver near one of the open cases is
        # useful even if the agency's other cases are across the county.
        features["geo_proximity_miles"] = min(distances)

    availability = applicant.availability or {}
    if isinstance(availability, dict) and availability.get("days"):
        days = availability["days"]
        if isinstance(days, list) and days:
            features["availability_overlap"] = min(1.0, len(days) / 5.0)

    return features


async def ranking_display_enabled(session: AsyncSession, agency_id: uuid.UUID) -> bool:
    """Whether this agency is past its ranking shadow period.

    False means the scorer still runs and still persists — the bias audit needs those rows —
    and nothing derived from it reaches a screen. A missing agency row resolves to False for
    the same reason everything else here fails closed: the safe answer to "should an unaudited
    model influence this hire?" is no.
    """
    enabled = (
        await session.execute(select(Agency.ranking_display_enabled).where(Agency.id == agency_id))
    ).scalar_one_or_none()
    return bool(enabled)


#: Bias-audit outcomes that may end a shadow period. `inconclusive` is excluded on purpose:
#: the usual reason a fairness audit is inconclusive is too small a sample, and "we could not
#: tell" is not the same finding as "we looked and it was fine".
AUDIT_OUTCOMES_PERMITTING_DISPLAY = frozenset({"passed", "passed_with_findings"})


async def enable_ranking_display(session: AsyncSession, *, principal: Principal) -> Agency:
    """End an agency's ranking shadow period, if a bias audit stands behind it.

    Refuses unless a recorded `ai_hiring_bias_audit` review exists and passed. That check is
    the entire value of the flag: a boolean anyone can set is a preference, and what
    `06_Compliance_and_Regulatory_Requirements.md` Section 5 requires is that the audit
    happened first. Here the code will not let it happen second.
    """
    from careos.modules.audit import compliance_log
    from careos.modules.audit.compliance_log_models import ReviewType

    statuses = {s.review_type: s for s in await compliance_log.review_status(session)}
    audit = statuses.get(ReviewType.ai_hiring_bias_audit.value)
    if audit is None or audit.never_performed:
        raise ConflictError(
            "Ranking display cannot be enabled before a bias audit has been recorded",
            details={
                "review_type": ReviewType.ai_hiring_bias_audit.value,
                "remediation": (
                    "Run `python -m careos.scripts.run_bias_audit` against this agency's real "
                    "hiring outcomes. It records the review on success."
                ),
            },
        )
    if audit.last_outcome not in AUDIT_OUTCOMES_PERMITTING_DISPLAY:
        raise ConflictError(
            "The most recent bias audit does not permit enabling ranking display",
            details={
                "last_outcome": audit.last_outcome,
                "last_performed_on": (
                    audit.last_performed_on.isoformat() if audit.last_performed_on else None
                ),
                "permitted": sorted(AUDIT_OUTCOMES_PERMITTING_DISPLAY),
            },
        )

    agency = await session.get(Agency, principal.agency_id)
    if agency is None:
        raise NotFoundError("Agency not found")
    if agency.ranking_display_enabled:
        return agency

    agency.ranking_display_enabled = True
    agency.ranking_display_enabled_at = datetime.now(UTC)
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.ranking_display_enabled,
        entity_type="agency",
        entity_id=agency.id,
        before_state={"ranking_display_enabled": False},
        after_state={
            "ranking_display_enabled": True,
            "bias_audit_performed_on": (
                audit.last_performed_on.isoformat() if audit.last_performed_on else None
            ),
            "bias_audit_outcome": audit.last_outcome,
        },
    )
    return agency


async def rank_applicants(
    session: AsyncSession,
    *,
    principal: Principal,
    job_posting_id: uuid.UUID | None = None,
) -> list[ApplicantProfile]:
    """Score and persist rankings for a posting's applicants (US-1.2.2).

    Always scores, whether or not the agency displays the result. That is what makes a
    shadow period produce anything: the bias audit reads `applicant_profile.ranking_score`
    against real hiring outcomes, so an agency that skipped scoring during the shadow period
    would reach the end of it with nothing to audit.
    """
    posting = None
    if job_posting_id is not None:
        posting = await session.get(JobPosting, job_posting_id)
        if posting is None:
            raise NotFoundError("Job posting not found")

    query = select(ApplicantProfile).where(
        ApplicantProfile.pipeline_stage.in_([PipelineStage.applied, PipelineStage.screened])
    )
    if job_posting_id is not None:
        query = query.where(ApplicantProfile.job_posting_id == job_posting_id)
    applicants = (await session.execute(query)).scalars().all()

    locations, open_count = await _open_shift_context(session, posting)
    required = list(posting.required_credential_types) if posting else []

    for applicant in applicants:
        features = build_applicant_features(
            applicant,
            required_credentials=required,
            open_shift_locations=locations,
            open_shift_count=open_count,
        )
        score = applicant_scorer.score(features)
        applicant.ranking_score = Decimal(str(score.value))
        # Score and factors are written together, always. The database rejects the row
        # otherwise (ck_applicant_ranking_score_requires_factors).
        applicant.ranking_factors = score.as_payload()
        applicant.ranked_at = datetime.now(UTC)
        applicant.ranking_model_version = score.model_version

    await session.flush()

    display_enabled = await ranking_display_enabled(session, principal.agency_id)

    if applicants:
        await record_audit(
            session,
            principal=principal,
            agency_id=principal.agency_id,
            action=AuditAction.applicants_ranked,
            entity_type="job_posting",
            entity_id=job_posting_id,
            after_state={
                "ranked_count": len(applicants),
                "model_version": applicant_scorer.model_version,
                # The evidence for the shadow period. A claim that scores were computed and
                # never shown is worth nothing if the only record of it is a config value
                # that can be flipped afterwards; this row is written at the moment it was
                # true (`13_Phase_1_Launch_Plan.md` 6.3).
                "ranking_displayed": display_enabled,
            },
        )

    if not display_enabled:
        # Application order, which is not derived from the model. Returning score order and
        # merely blanking the numbers would leak the ranking through the list itself — the
        # top of a list is a recommendation whether or not it carries a number.
        return sorted(applicants, key=lambda a: a.created_at)

    return sorted(
        applicants,
        key=lambda a: a.ranking_score if a.ranking_score is not None else Decimal(0),
        reverse=True,
    )


async def advance_stage(
    session: AsyncSession,
    *,
    principal: Principal,
    applicant: ApplicantProfile,
    to_stage: PipelineStage,
) -> ApplicantProfile:
    """Move an applicant through the funnel, rejecting invalid transitions."""
    permitted = ALLOWED_TRANSITIONS[applicant.pipeline_stage]
    if to_stage not in permitted:
        raise ConflictError(
            f"Cannot move an applicant from {applicant.pipeline_stage.value} to {to_stage.value}",
            details={
                "current_stage": applicant.pipeline_stage.value,
                "allowed": sorted(s.value for s in permitted),
            },
        )

    before = {"pipeline_stage": applicant.pipeline_stage.value}
    applicant.pipeline_stage = to_stage
    applicant.stage_changed_at = datetime.now(UTC)
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.applicant_stage_changed,
        entity_type="applicant_profile",
        entity_id=applicant.id,
        before_state=before,
        after_state={"pipeline_stage": to_stage.value},
    )
    return applicant


async def hire_applicant(
    session: AsyncSession,
    *,
    principal: Principal,
    applicant: ApplicantProfile,
) -> Caregiver:
    """Convert an applicant into a caregiver record, starting onboarding (US-1.2.x → 1.3).

    The new caregiver starts with `exclusion_check_status = not_run`, so they cannot be
    scheduled onto a publicly-funded visit until screening clears (US-1.3.2). Hiring someone
    and being allowed to send them into a Medicaid client's home are deliberately separate
    events.
    """
    if applicant.pipeline_stage is PipelineStage.hired:
        existing = (
            await session.execute(
                select(Caregiver).where(Caregiver.applicant_profile_id == applicant.id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    await advance_stage(
        session, principal=principal, applicant=applicant, to_stage=PipelineStage.hired
    )

    caregiver = Caregiver(
        agency_id=principal.agency_id,
        applicant_profile_id=applicant.id,
        legal_name=applicant.full_name,
        geo_lat=applicant.geo_lat,
        geo_lng=applicant.geo_lng,
        employment_status=EmploymentStatus.onboarding,
        exclusion_check_status=ExclusionCheckStatus.not_run,
    )
    session.add(caregiver)
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.applicant_hired,
        entity_type="caregiver",
        entity_id=caregiver.id,
        after_state={
            "applicant_profile_id": str(applicant.id),
            "employment_status": caregiver.employment_status.value,
        },
    )
    return caregiver


async def recruiting_funnel(
    session: AsyncSession, *, job_posting_id: uuid.UUID | None = None
) -> list[FunnelStage]:
    """Applied → screened → offer → hired, with stage-to-stage conversion (US-1.2.4).

    Counts are cumulative: someone who reached `hired` also counts as having been screened,
    because otherwise "conversion" would measure who is currently sitting in a stage rather
    than who progressed through it.
    """
    query = select(ApplicantProfile.pipeline_stage, func.count()).group_by(
        ApplicantProfile.pipeline_stage
    )
    if job_posting_id is not None:
        query = query.where(ApplicantProfile.job_posting_id == job_posting_id)
    # Indexed rather than unpacked: SQLAlchemy's Row is not typed as a plain tuple, so
    # `dict(rows)` and `{k: v for k, v in rows}` each upset one of ruff or mypy.
    rows = (await session.execute(query)).all()
    raw: dict[PipelineStage, int] = {row[0]: row[1] for row in rows}

    counts = {stage: raw.get(stage, 0) for stage in PipelineStage}
    progression = [
        PipelineStage.applied,
        PipelineStage.screened,
        PipelineStage.offer,
        PipelineStage.hired,
    ]

    cumulative: dict[PipelineStage, int] = {}
    for index, stage in enumerate(progression):
        cumulative[stage] = sum(counts[s] for s in progression[index:])
    # Rejected applicants entered the funnel and must be counted at the top, or the
    # applied→screened conversion rate is flattering nonsense.
    cumulative[PipelineStage.applied] += counts[PipelineStage.rejected]

    stages: list[FunnelStage] = []
    for index, stage in enumerate(progression):
        previous = cumulative[progression[index - 1]] if index > 0 else None
        stages.append(
            FunnelStage(
                stage=stage.value,
                count=cumulative[stage],
                conversion_from_previous=(
                    round(cumulative[stage] / previous, 4) if previous else None
                ),
            )
        )
    return stages
