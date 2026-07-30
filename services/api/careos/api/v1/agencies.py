"""Agency profile and user management (`05_API_Specification.md` Section 2).

Each handler declares its permitted roles by taking `Depends(requires(...))` as its
principal parameter. That single declaration both enforces the roles and satisfies the
startup check in `careos.core.rbac.assert_all_routes_declare_access`, so there is no way to
add a route here that silently ends up with no access rules.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.api import schemas
from careos.api.deps import db_session
from careos.core.audit import AuditAction, record_audit
from careos.core.errors import NotFoundError, PermissionDeniedError
from careos.core.rbac import requires
from careos.core.security import Principal
from careos.modules.agency import service as agency_service
from careos.modules.agency.models import Agency, AppUser, Role
from careos.modules.audit import compliance_log

router = APIRouter(tags=["agency"])

#: Every role that may read agency-level configuration.
_ALL_STAFF = (
    Role.owner_admin,
    Role.scheduler,
    Role.clinical_supervisor,
    Role.billing_rcm,
    Role.auditor,
)


def _assert_own_agency(principal: Principal, agency_id: uuid.UUID) -> None:
    """Reject a path parameter naming another tenant.

    RLS already makes the row unreadable, so this exists to return a clear 403 rather than a
    confusing 404, and to keep the intent legible at the call site.
    """
    if agency_id != principal.agency_id:
        raise PermissionDeniedError("You cannot access another agency's data")


@router.get("/agencies/{agency_id}", response_model=schemas.AgencyOut)
async def get_agency(
    agency_id: uuid.UUID,
    principal: Principal = Depends(requires(*_ALL_STAFF)),
    session: AsyncSession = Depends(db_session),
) -> schemas.AgencyOut:
    _assert_own_agency(principal, agency_id)
    agency = await session.get(Agency, agency_id)
    if agency is None:
        raise NotFoundError("Agency not found")
    return schemas.AgencyOut.model_validate(agency)


@router.patch("/agencies/{agency_id}", response_model=schemas.AgencyOut)
async def update_agency(
    agency_id: uuid.UUID,
    payload: schemas.AgencyUpdate,
    principal: Principal = Depends(requires(Role.owner_admin)),
    session: AsyncSession = Depends(db_session),
) -> schemas.AgencyOut:
    _assert_own_agency(principal, agency_id)
    agency = await session.get(Agency, agency_id)
    if agency is None:
        raise NotFoundError("Agency not found")

    before = {
        "legal_name": agency.legal_name,
        "service_states": list(agency.service_states),
        "service_lines": list(agency.service_lines),
        "accepted_payer_types": list(agency.accepted_payer_types),
    }
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(agency, field_name, value)
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=agency.id,
        action=AuditAction.agency_updated,
        entity_type="agency",
        entity_id=agency.id,
        before_state=before,
        after_state=payload.model_dump(exclude_unset=True),
    )
    return schemas.AgencyOut.model_validate(agency)


@router.post("/agencies/{agency_id}/users", response_model=schemas.UserOut, status_code=201)
async def invite_user(
    agency_id: uuid.UUID,
    payload: schemas.UserInvite,
    principal: Principal = Depends(requires(Role.owner_admin)),
    session: AsyncSession = Depends(db_session),
) -> schemas.UserOut:
    _assert_own_agency(principal, agency_id)
    user = await agency_service.invite_user(
        session,
        principal=principal,
        email=payload.email,
        role=payload.role,
        phone=payload.phone,
        initial_password=payload.initial_password,
    )
    return schemas.UserOut.model_validate(user)


@router.get("/agencies/{agency_id}/users", response_model=list[schemas.UserOut])
async def list_users(
    agency_id: uuid.UUID,
    principal: Principal = Depends(requires(Role.owner_admin, Role.auditor)),
    session: AsyncSession = Depends(db_session),
) -> list[schemas.UserOut]:
    _assert_own_agency(principal, agency_id)
    users = (await session.execute(select(AppUser).order_by(AppUser.created_at))).scalars().all()
    return [schemas.UserOut.model_validate(u) for u in users]


@router.patch("/users/{user_id}/role", response_model=schemas.UserOut)
async def change_role(
    user_id: uuid.UUID,
    payload: schemas.RoleChange,
    principal: Principal = Depends(requires(Role.owner_admin)),
    session: AsyncSession = Depends(db_session),
) -> schemas.UserOut:
    user = await session.get(AppUser, user_id)
    if user is None:
        raise NotFoundError("User not found")

    # An owner demoting themselves could leave the tenant with nobody able to administer it,
    # recoverable only by support intervention.
    if user.id == principal.user_id and payload.role is not Role.owner_admin:
        raise PermissionDeniedError("You cannot change your own role away from owner_admin")

    before = {"role": user.role.value}
    user.role = payload.role
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.user_role_changed,
        entity_type="app_user",
        entity_id=user.id,
        before_state=before,
        after_state={"role": payload.role.value},
    )
    return schemas.UserOut.model_validate(user)


@router.post("/users/{user_id}/revoke-sessions", response_model=schemas.UserOut)
async def revoke_sessions(
    user_id: uuid.UUID,
    payload: schemas.RevokeSessions,
    principal: Principal = Depends(requires(Role.owner_admin)),
    session: AsyncSession = Depends(db_session),
) -> schemas.UserOut:
    """End every outstanding session for a user, effective on the next request they make.

    The admin-facing half of the remote-wipe requirement in `08_Security_Architecture.md`
    Section 6. Revoking does not delete the account or change the password — it invalidates
    issued tokens, which is what is needed when a phone is lost or a caregiver is suspended
    pending investigation and may yet come back.

    Self-revocation is allowed: it signs the caller out everywhere, which is exactly what
    someone whose own laptop was stolen needs, and unlike a role change it locks nobody out
    permanently — they can sign in again.
    """
    user = await session.get(AppUser, user_id)
    if user is None:
        raise NotFoundError("User not found")

    await agency_service.revoke_sessions(
        session, principal=principal, user=user, reason=payload.reason
    )
    return schemas.UserOut.model_validate(user)


@router.get(
    "/agencies/{agency_id}/compliance-reviews", response_model=list[schemas.ReviewStatusOut]
)
async def compliance_reviews(
    agency_id: uuid.UUID,
    principal: Principal = Depends(requires(Role.owner_admin, Role.auditor)),
    session: AsyncSession = Depends(db_session),
) -> list[schemas.ReviewStatusOut]:
    """Standing of every compliance review this agency owes.

    Enumerates the full cadence from `06_Compliance_and_Regulatory_Requirements.md` Section 9,
    including reviews that have never been performed — those show as `never_performed` rather
    than being absent, so a gap cannot hide behind an empty list.
    """
    _assert_own_agency(principal, agency_id)
    statuses = await compliance_log.review_status(session)
    return [
        schemas.ReviewStatusOut(
            review_type=s.review_type,
            last_performed_on=s.last_performed_on,
            last_outcome=s.last_outcome,
            next_due_on=s.next_due_on,
            is_overdue=s.is_overdue,
            never_performed=s.never_performed,
        )
        for s in statuses
    ]
