"""Recruiting endpoints (`05_API_Specification.md` Section 3)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.api import schemas
from careos.api.deps import db_session
from careos.core.errors import NotFoundError
from careos.core.rbac import requires
from careos.core.security import Principal
from careos.modules.agency.models import Role
from careos.modules.recruiting import service as recruiting
from careos.modules.recruiting.models import ApplicantProfile, JobPosting, PipelineStage

router = APIRouter(tags=["recruiting"])


@router.post("/job-postings", response_model=schemas.JobPostingOut, status_code=201)
async def create_job_posting(
    payload: schemas.JobPostingCreate,
    principal: Principal = Depends(requires(Role.owner_admin, Role.scheduler)),
    session: AsyncSession = Depends(db_session),
) -> schemas.JobPostingOut:
    posting = await recruiting.create_job_posting(
        session,
        principal=principal,
        title=payload.title,
        description=payload.description,
        required_credential_types=payload.required_credential_types,
        service_state=payload.service_state,
    )
    return schemas.JobPostingOut.model_validate(posting)


@router.get("/job-postings", response_model=list[schemas.JobPostingOut])
async def list_job_postings(
    principal: Principal = Depends(requires(Role.owner_admin, Role.scheduler, Role.auditor)),
    session: AsyncSession = Depends(db_session),
) -> list[schemas.JobPostingOut]:
    rows = (
        (await session.execute(select(JobPosting).order_by(JobPosting.created_at.desc())))
        .scalars()
        .all()
    )
    return [schemas.JobPostingOut.model_validate(p) for p in rows]


@router.post("/applicants", response_model=schemas.ApplicantOut, status_code=201)
async def create_applicant(
    payload: schemas.ApplicantCreate,
    principal: Principal = Depends(requires(Role.owner_admin, Role.scheduler)),
    session: AsyncSession = Depends(db_session),
) -> schemas.ApplicantOut:
    """Ingest an applicant from any source into the single pipeline (US-1.2.1)."""
    applicant = await recruiting.ingest_applicant(
        session,
        principal=principal,
        job_posting_id=payload.job_posting_id,
        source=payload.source,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        claimed_credentials=payload.claimed_credentials,
        availability=payload.availability,
        geo_lat=payload.geo_lat,
        geo_lng=payload.geo_lng,
    )
    return schemas.ApplicantOut.model_validate(applicant)


@router.get("/job-postings/{job_posting_id}/applicants", response_model=list[schemas.ApplicantOut])
async def list_applicants_for_posting(
    job_posting_id: uuid.UUID,
    principal: Principal = Depends(requires(Role.owner_admin, Role.scheduler, Role.auditor)),
    session: AsyncSession = Depends(db_session),
    rank: bool = Query(
        default=True,
        description="Re-score before returning. Set false for a read-only view that does "
        "not write new ranking rows.",
    ),
) -> list[schemas.ApplicantOut]:
    """Applicants with AI ranking scores and their explanatory factors (US-1.2.2)."""
    if await session.get(JobPosting, job_posting_id) is None:
        raise NotFoundError("Job posting not found")

    if rank:
        ranked = await recruiting.rank_applicants(
            session, principal=principal, job_posting_id=job_posting_id
        )
        return [schemas.ApplicantOut.model_validate(a) for a in ranked]

    rows = (
        (
            await session.execute(
                select(ApplicantProfile)
                .where(ApplicantProfile.job_posting_id == job_posting_id)
                .order_by(ApplicantProfile.ranking_score.desc().nullslast())
            )
        )
        .scalars()
        .all()
    )
    return [schemas.ApplicantOut.model_validate(a) for a in rows]


@router.post("/applicants/{applicant_id}/stage", response_model=schemas.ApplicantOut)
async def change_stage(
    applicant_id: uuid.UUID,
    payload: schemas.StageChange,
    principal: Principal = Depends(requires(Role.owner_admin, Role.scheduler)),
    session: AsyncSession = Depends(db_session),
) -> schemas.ApplicantOut:
    applicant = await session.get(ApplicantProfile, applicant_id)
    if applicant is None:
        raise NotFoundError("Applicant not found")
    updated = await recruiting.advance_stage(
        session,
        principal=principal,
        applicant=applicant,
        to_stage=PipelineStage(payload.stage),
    )
    return schemas.ApplicantOut.model_validate(updated)


@router.post(
    "/applicants/{applicant_id}/hire", response_model=schemas.CaregiverOut, status_code=201
)
async def hire(
    applicant_id: uuid.UUID,
    principal: Principal = Depends(requires(Role.owner_admin)),
    session: AsyncSession = Depends(db_session),
) -> schemas.CaregiverOut:
    """Convert an applicant to a caregiver and begin onboarding.

    The resulting caregiver still cannot be scheduled onto a publicly-funded visit until
    their exclusion check clears (US-1.3.2).
    """
    applicant = await session.get(ApplicantProfile, applicant_id)
    if applicant is None:
        raise NotFoundError("Applicant not found")
    caregiver = await recruiting.hire_applicant(session, principal=principal, applicant=applicant)
    return schemas.CaregiverOut.model_validate(caregiver)


@router.get("/reports/recruiting-funnel", response_model=list[schemas.FunnelStageOut])
async def funnel(
    principal: Principal = Depends(requires(Role.owner_admin, Role.scheduler, Role.auditor)),
    session: AsyncSession = Depends(db_session),
    job_posting_id: uuid.UUID | None = Query(default=None),
) -> list[schemas.FunnelStageOut]:
    """Applied → screened → offer → hired with conversion rates (US-1.2.4)."""
    stages = await recruiting.recruiting_funnel(session, job_posting_id=job_posting_id)
    return [
        schemas.FunnelStageOut(
            stage=s.stage, count=s.count, conversion_from_previous=s.conversion_from_previous
        )
        for s in stages
    ]
