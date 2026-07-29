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
