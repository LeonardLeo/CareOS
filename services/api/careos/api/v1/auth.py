"""Authentication and agency provisioning endpoints (`05_API_Specification.md` Section 2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from careos.api import schemas
from careos.api.deps import db_session
from careos.config import get_settings
from careos.core.context import source_ip_var
from careos.core.errors import (
    AccountInactiveError,
    AuthenticationError,
    MFAInvalidCodeError,
    MFARequiredError,
    RateLimitExceededError,
)
from careos.core.ratelimit import get_rate_limiter
from careos.core.rbac import public, requires
from careos.core.security import Principal, create_token, decode_token
from careos.db.session import privileged_session, tenant_session
from careos.modules.agency import service as agency_service
from careos.modules.agency.models import (
    MFA_ELIGIBLE_ROLES,
    MFA_REQUIRED_ROLES,
    AppUser,
    Role,
)

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
            # Inside the same transaction as the credential check, because a successful TOTP
            # verification *writes*: the counter that stops the same code being replayed, and
            # the spending of a recovery code. Verifying and forgetting would leave both
            # single-use guarantees as comments.
            agency_service.assert_mfa_satisfied(user, code=payload.mfa_code)
            user_id, agency_id, role = user.id, user.agency_id, user.role
            mfa_satisfied = user.mfa_enrolled or role not in MFA_REQUIRED_ROLES
    except MFAInvalidCodeError:
        # A valid password and a wrong code. Recorded: that is somebody guessing at the second
        # factor while holding the first, which is precisely what the audit trail is for.
        async with privileged_session() as session:
            await agency_service.record_failed_login(session, email=payload.email)
        raise
    except MFARequiredError:
        # No code supplied. Not a failure — it is the first half of a normal sign-in, since a
        # client cannot know an account is enrolled until it tries. Recording it would write a
        # "login failed" row per enrolled person per day and bury the ones that matter.
        raise
    except AuthenticationError:
        async with privileged_session() as session:
            await agency_service.record_failed_login(session, email=payload.email)
        raise

    async with tenant_session(agency_id) as session:
        caregiver_id = await agency_service.complete_login(
            session, user_id=user_id, agency_id=agency_id, role=role
        )

    # A privileged user who has not enrolled still gets a session — it can reach the enrolment
    # endpoints and nothing else. Refusing the login outright would be unsatisfiable: the only
    # way to enrol is through an authenticated call made before enrolling.
    access = create_token(
        user_id=user_id,
        agency_id=agency_id,
        role=role,
        token_type="access",
        caregiver_id=caregiver_id,
        mfa_satisfied=mfa_satisfied,
    )
    refresh_token = create_token(
        user_id=user_id,
        agency_id=agency_id,
        role=role,
        token_type="refresh",
        caregiver_id=caregiver_id,
        mfa_satisfied=mfa_satisfied,
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


@router.post("/auth/mfa/enroll", response_model=schemas.MFAEnrolmentStarted)
async def start_mfa_enrolment(
    payload: schemas.MFAEnrolStart | None = None,
    principal: Principal = Depends(requires(*MFA_ELIGIBLE_ROLES, mfa_exempt=True)),
    session: AsyncSession = Depends(db_session),
) -> schemas.MFAEnrolmentStarted:
    """Begin enrolling an authenticator for the calling user.

    Three roles must enrol; every role that has a client able to *ask* for a code may. That
    excludes `caregiver` today, and the exclusion is a guard rather than a policy: the
    caregiver app has no field for a code, so a caregiver who enrolled through the API would
    lock themselves out of the phone they clock in with — at a client's door, with no way to
    fix it themselves. `08_Security_Architecture.md` Section 1 wants this extended to
    schedulers next; that is a one-line change to `MFA_ELIGIBLE_ROLES` once the app catches up.

    `mfa_exempt` because this is the endpoint an unenrolled privileged user must reach in
    order to stop being unenrolled. It is one of exactly two routes with that exemption.

    Re-enrolling replaces any previous secret and recovery codes, and clears the enrolled flag
    until a code is confirmed — so an abandoned enrolment cannot leave an account holding a
    secret nobody has. An account that is **already** enrolled must send `current_code`: moving
    a second factor to a new device is an authentication, and without that check a stolen
    session is enough to move it to the thief's.
    """
    user = await session.get(AppUser, principal.user_id)
    if user is None:
        raise AuthenticationError("This account is no longer active")

    secret, uri, recovery_codes = await agency_service.begin_mfa_enrolment(
        session,
        principal=principal,
        user=user,
        current_code=payload.current_code if payload else None,
    )
    return schemas.MFAEnrolmentStarted(
        secret=secret, otpauth_uri=uri, recovery_codes=recovery_codes
    )


@router.post("/auth/mfa/confirm", response_model=schemas.TokenPair)
async def confirm_mfa_enrolment(
    payload: schemas.MFAConfirm,
    principal: Principal = Depends(requires(*MFA_ELIGIBLE_ROLES, mfa_exempt=True)),
    session: AsyncSession = Depends(db_session),
) -> schemas.TokenPair:
    """Finish enrolment by proving a code, and return a session that satisfies the requirement.

    **A new token pair rather than an upgrade of the one in hand**, because a claim inside a
    signed token cannot be changed after the fact — and should not be: "this session passed
    MFA" stays a statement about how the session was established. Minting it here is exactly
    as strong as minting it at login, since both happen only after a code has been proved.

    The alternative — telling the user to sign in again — reads as a small ask and is not one.
    The code they just typed is spent, so their next sign-in fails until the following
    thirty-second window, at the one moment they are most likely to conclude the feature is
    broken.
    """
    user = await session.get(AppUser, principal.user_id)
    if user is None:
        raise AuthenticationError("This account is no longer active")

    await agency_service.confirm_mfa_enrolment(
        session, principal=principal, user=user, code=payload.code
    )
    access, refresh_token = agency_service.issue_tokens(user, principal.caregiver_id)
    return schemas.TokenPair(
        access_token=access,
        refresh_token=refresh_token,
        expires_in=get_settings().access_token_ttl_seconds,
    )


@router.get("/auth/me", response_model=schemas.UserOut)
async def whoami(
    principal: Principal = Depends(requires(*Role, mfa_exempt=True)),
    session: AsyncSession = Depends(db_session),
) -> schemas.UserOut:
    """The caller's own user record.

    Exists because a client cannot otherwise learn its own MFA state: the user list is
    owner-admin and auditor only, correctly, so a clinical supervisor had no way to find out
    whether they were enrolled — and therefore no way to know whether to ask for the current
    code before replacing an authenticator.

    `mfa_exempt` for the same reason the enrolment routes are: a session held to the enrolment
    screen has to be able to render that screen.
    """
    user = await session.get(AppUser, principal.user_id)
    if user is None:
        raise AuthenticationError("This account is no longer active")
    return schemas.UserOut.model_validate(user)
