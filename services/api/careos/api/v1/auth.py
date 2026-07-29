"""Authentication and agency provisioning endpoints (`05_API_Specification.md` Section 2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from careos.api import schemas
from careos.config import get_settings
from careos.core.errors import AuthenticationError
from careos.core.rbac import public
from careos.core.security import create_token, decode_token
from careos.db.session import privileged_session, tenant_session
from careos.modules.agency import service as agency_service
from careos.modules.agency.models import AppUser

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=schemas.TokenPair, dependencies=[Depends(public())])
async def login(payload: schemas.LoginRequest) -> schemas.TokenPair:
    """Exchange credentials for a token pair.

    Split across two sessions on purpose. Credential verification must cross tenants — the
    tenant is what the email resolves to — so it runs on the narrow privileged pool. Once
    the tenant is known, everything else moves to an ordinary tenant-scoped session, keeping
    the privileged role's grants down to `agency`, `app_user`, and `audit_log`.
    """
    try:
        async with privileged_session() as session:
            user = await agency_service.verify_credentials(
                session, email=payload.email, password=payload.password
            )
            user_id, agency_id, role = user.id, user.agency_id, user.role
    except AuthenticationError:
        async with privileged_session() as session:
            await agency_service.record_failed_login(session, email=payload.email)
        raise

    async with tenant_session(agency_id) as session:
        caregiver_id = await agency_service.complete_login(
            session, user_id=user_id, agency_id=agency_id, role=role
        )

    access = create_token(
        user_id=user_id,
        agency_id=agency_id,
        role=role,
        token_type="access",
        caregiver_id=caregiver_id,
    )
    refresh_token = create_token(
        user_id=user_id,
        agency_id=agency_id,
        role=role,
        token_type="refresh",
        caregiver_id=caregiver_id,
    )
    return schemas.TokenPair(
        access_token=access,
        refresh_token=refresh_token,
        expires_in=get_settings().access_token_ttl_seconds,
    )


@router.post("/auth/refresh", response_model=schemas.TokenPair, dependencies=[Depends(public())])
async def refresh(payload: schemas.RefreshRequest) -> schemas.TokenPair:
    principal = decode_token(payload.refresh_token, expected_type="refresh")
    async with privileged_session() as session:
        user = await session.get(AppUser, principal.user_id)
        # Re-read the user rather than trusting the token's claims. A role change or a
        # suspension between issuing and refreshing must take effect at refresh, otherwise
        # a revoked account keeps working for the refresh token's full lifetime.
        if user is None or user.status.value != "active":
            raise AuthenticationError("This account is no longer active")
        access, new_refresh = agency_service.issue_tokens(user, principal.caregiver_id)
    return schemas.TokenPair(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=get_settings().access_token_ttl_seconds,
    )


@router.post(
    "/agencies",
    response_model=schemas.AgencyOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(public())],
)
async def create_agency(payload: schemas.AgencyCreate) -> schemas.AgencyOut:
    """Self-serve tenant creation (the onboarding wizard in US-1.1.1).

    Public by necessity: there is no tenant to authenticate against yet. In a deployment
    that sells through a sales-assisted motion this would move behind an internal
    provisioning role instead.
    """
    async with privileged_session() as session:
        agency, _owner = await agency_service.create_agency(
            session,
            legal_name=payload.legal_name,
            tax_id=payload.tax_id,
            service_states=payload.service_states,
            service_lines=list(payload.service_lines),
            accepted_payer_types=list(payload.accepted_payer_types),
            owner_email=payload.owner_email,
            owner_password=payload.owner_password,
        )
        return schemas.AgencyOut.model_validate(agency)
