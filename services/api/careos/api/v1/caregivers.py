"""Caregiver records and exclusion screening (`05_API_Specification.md` Section 3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.api import schemas
from careos.api.deps import db_session
from careos.core import idempotency
from careos.core.audit import AuditAction, record_audit
from careos.core.crypto import encrypt_field
from careos.core.errors import NotFoundError
from careos.core.rbac import requires
from careos.core.security import Principal
from careos.modules.agency.models import Role
from careos.modules.credentialing.models import (
    Caregiver,
    EmploymentStatus,
    ExclusionCheckStatus,
    ScreeningRequest,
)

router = APIRouter(tags=["caregivers"])


@router.post("/caregivers", response_model=schemas.CaregiverOut, status_code=201)
async def create_caregiver(
    payload: schemas.CaregiverCreate,
    principal: Principal = Depends(requires(Role.owner_admin, Role.scheduler)),
    session: AsyncSession = Depends(db_session),
) -> schemas.CaregiverOut:
    caregiver = Caregiver(
        agency_id=principal.agency_id,
        app_user_id=payload.app_user_id,
        legal_name=payload.legal_name,
        dob_encrypted=encrypt_field(payload.dob.isoformat() if payload.dob else None),
        address_encrypted=encrypt_field(payload.address),
        geo_lat=payload.geo_lat,
        geo_lng=payload.geo_lng,
        employment_status=EmploymentStatus.onboarding,
        # Explicit rather than implied: a new caregiver has not been screened, and the
        # scheduling gate depends on this being accurate rather than optimistic.
        exclusion_check_status=ExclusionCheckStatus.not_run,
    )
    session.add(caregiver)
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.caregiver_created,
        entity_type="caregiver",
        entity_id=caregiver.id,
        after_state={"legal_name": caregiver.legal_name},
    )
    return schemas.CaregiverOut.model_validate(caregiver)


@router.get("/caregivers", response_model=list[schemas.CaregiverOut])
async def list_caregivers(
    principal: Principal = Depends(
        requires(Role.owner_admin, Role.scheduler, Role.clinical_supervisor, Role.auditor)
    ),
    session: AsyncSession = Depends(db_session),
) -> list[schemas.CaregiverOut]:
    rows = (await session.execute(select(Caregiver).order_by(Caregiver.legal_name))).scalars().all()
    return [schemas.CaregiverOut.model_validate(c) for c in rows]


@router.get("/caregivers/{caregiver_id}", response_model=schemas.CaregiverOut)
async def get_caregiver(
    caregiver_id: uuid.UUID,
    principal: Principal = Depends(
        requires(Role.owner_admin, Role.scheduler, Role.clinical_supervisor, Role.auditor)
    ),
    session: AsyncSession = Depends(db_session),
) -> schemas.CaregiverOut:
    caregiver = await session.get(Caregiver, caregiver_id)
    if caregiver is None:
        raise NotFoundError("Caregiver not found")
    return schemas.CaregiverOut.model_validate(caregiver)


@router.post(
    "/caregivers/{caregiver_id}/exclusion-check",
    response_model=schemas.CaregiverOut,
)
async def record_exclusion_check(
    caregiver_id: uuid.UUID,
    payload: schemas.ExclusionCheckResult,
    principal: Principal = Depends(requires(Role.owner_admin)),
    session: AsyncSession = Depends(db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> schemas.CaregiverOut:
    """Record the outcome of an OIG LEIE / GSA SAM exclusion screening.

    This is the field that gates Medicaid- and Medicare-billed scheduling (PRD US-1.3.2), so
    it gets its own audited endpoint restricted to owner/admin rather than being settable
    through a general caregiver update.

    `exclusion_checked_at` is stamped on every result because exclusion status is not
    check-once — `07_Integration_Specifications.md` Section 3 expects recurring
    re-verification, and that needs a timestamp to schedule against.
    """
    outcome = await idempotency.claim(
        session,
        principal=principal,
        key=idempotency_key,
        endpoint="caregivers.exclusion_check",
        payload={"caregiver_id": str(caregiver_id), **payload.model_dump(mode="json")},
    )
    if outcome.is_replay:
        return schemas.CaregiverOut.model_validate(outcome.replayed_body)

    caregiver = await session.get(Caregiver, caregiver_id)
    if caregiver is None:
        raise NotFoundError("Caregiver not found")

    before = {
        "exclusion_check_status": caregiver.exclusion_check_status.value,
        "exclusion_checked_at": (
            caregiver.exclusion_checked_at.isoformat() if caregiver.exclusion_checked_at else None
        ),
    }
    caregiver.exclusion_check_status = ExclusionCheckStatus(payload.status)
    caregiver.exclusion_checked_at = datetime.now(UTC)
    if caregiver.exclusion_check_status is ExclusionCheckStatus.cleared:
        caregiver.employment_status = EmploymentStatus.active

    session.add(
        ScreeningRequest(
            agency_id=principal.agency_id,
            caregiver_id=caregiver.id,
            vendor_key=payload.vendor_key,
            check_types=["oig_leie", "gsa_sam"],
            vendor_request_id=payload.vendor_reference,
            status="completed",
            result_payload={"status": payload.status},
            completed_at=caregiver.exclusion_checked_at,
        )
    )
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.exclusion_check_recorded,
        entity_type="caregiver",
        entity_id=caregiver.id,
        before_state=before,
        after_state={
            "exclusion_check_status": caregiver.exclusion_check_status.value,
            "vendor_key": payload.vendor_key,
        },
    )

    body = schemas.CaregiverOut.model_validate(caregiver)
    assert outcome.record is not None
    await idempotency.complete(
        session, outcome.record, status=200, body=body.model_dump(mode="json")
    )
    return body
