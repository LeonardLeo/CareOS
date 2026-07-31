"""Authentication and agency provisioning endpoints (`05_API_Specification.md` Section 2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from careos.api import schemas
from careos.config import get_settings
from careos.core.context import source_ip_var
from careos.core.errors import (
    AccountInactiveError,
    AuthenticationError,
    RateLimitExceededError,
)
from careos.core.ratelimit import get_rate_limiter
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

    The per-account rate limit is applied here rather than in middleware because the email is
    in the request body, and reading a body in middleware consumes the receive stream before
    the handler can. The per-address limit still runs in front of this
    (`05_API_Specification.md` Section 9 plus the reasoning in `careos.core.ratelimit`).
    """
    # Counted before the password is checked, so a wrong guess costs allowance too. Charging
    # only failures would let an attacker with one valid credential probe indefinitely, and
    # charging only successes would not limit guessing at all.
    attempt = await get_rate_limiter().check_login_attempt(
        source_ip=source_ip_var.get(), email=payload.email
    )
    if not attempt.allowed:
        raise RateLimitExceededError(
            "Too many sign-in attempts for this account. Please wait and try again.",
            retry_after=attempt.retry_after,
            details={"limit_per_minute": attempt.limit},
        )

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
            # Same code as the login path so a client has one branch to write, not two. The
            # refresh token is proof of a prior sign-in, so this discloses nothing either.
            raise AccountInactiveError(
                "This account has been disabled. Contact your agency administrator."
            )
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
