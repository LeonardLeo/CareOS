"""The CareOS operator console's API (`08_Security_Architecture.md` Sections 1 and 2).

Every route here declares `requires_platform(...)` or `public()`, so the startup gate in
`careos.core.rbac` refuses to boot if one is added without an access rule — the same
guarantee the tenant routers get, from the same check.

Three properties are worth stating once rather than repeating per handler:

* **A tenant token cannot reach these endpoints and an operator token cannot reach the
  tenant ones.** Both are signed with the same key, and the `principal_type` claim plus two
  separate decoders is what keeps them apart. `careos.api.deps.authenticate` puts them on
  different request-state attributes, so a handler receives the wrong kind of principal never
  rather than sometimes.
* **MFA is unconditional.** `requires_platform` enforces it with no configuration flag, and
  the only exemptions are the enrolment pair and `/platform/me` — which an unenrolled
  operator needs in order to render the screen that lets them enrol.
* **The session runs as `careos_platform`**, through `platform_db_session`. That role's
  grants, not this file, decide what an operator can read.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from careos.api import schemas
from careos.api.deps import platform_db_session
from careos.config import get_settings
from careos.core.context import source_ip_var
from careos.core.errors import (
    AuthenticationError,
    MFAInvalidCodeError,
    MFARequiredError,
    RateLimitExceededError,
)
from careos.core.ratelimit import get_rate_limiter
from careos.core.rbac import public, requires_platform
from careos.core.security import PlatformPrincipal, decode_platform_token
from careos.db.session import platform_session
from careos.modules.platform import service as platform_service
from careos.modules.platform.models import (
    PlatformAuditAction,
    PlatformOperator,
    PlatformRole,
)

router = APIRouter(tags=["platform"], prefix="/platform")

#: Both operator roles. Named once so a route that should be readable by everyone in the
#: console cannot drift from the list.
_ANY_OPERATOR = (PlatformRole.platform_admin, PlatformRole.platform_support)


def _to_health_out(health: platform_service.AgencyHealth) -> schemas.AgencyHealthOut:
    # `asdict` rather than `vars`: `AgencyHealth` uses `slots=True` and therefore has no
    # `__dict__`. The field names are shared with the view's column tuple, so this stays a
    # one-liner rather than a mapping that would need updating alongside them.
    return schemas.AgencyHealthOut(**asdict(health))


@router.post(
    "/auth/login", response_model=schemas.TokenPair, dependencies=[Depends(public())]
)
async def platform_login(payload: schemas.PlatformLoginRequest) -> schemas.TokenPair:
    """Exchange operator credentials for a token pair.

    Rate limited twice, as the tenant login is: per address in middleware (the `auth` tier
    names this path), and per address-and-account here, where the email has been parsed.
    Counted before the password is checked, so a wrong guess costs allowance too.
    """
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
        async with platform_session() as session:
            operator = await platform_service.verify_operator_credentials(
                session, email=payload.email, password=payload.password
            )
            # Inside the same transaction as the credential check, because verifying a TOTP
            # code *writes*: the replay counter, and the spending of a recovery code.
            platform_service.assert_operator_mfa_satisfied(operator, code=payload.mfa_code)
            await platform_service.record_operator_login(session, operator=operator)
            access, refresh_token = platform_service.issue_operator_tokens(operator)
    except MFARequiredError as exc:
        # `MFAInvalidCodeError` subclasses this, and only the wrong-code case is a failure
        # worth recording: "no code supplied" is the first half of every normal sign-in, and
        # recording it would write one failure per operator per day.
        if isinstance(exc, MFAInvalidCodeError):
            async with platform_session() as session:
                await platform_service.record_failed_operator_login(session, email=payload.email)
        raise
    except AuthenticationError:
        async with platform_session() as session:
            await platform_service.record_failed_operator_login(session, email=payload.email)
        raise

    return schemas.TokenPair(
        access_token=access,
        refresh_token=refresh_token,
        expires_in=get_settings().access_token_ttl_seconds,
    )


@router.post(
    "/auth/refresh", response_model=schemas.TokenPair, dependencies=[Depends(public())]
)
async def platform_refresh(payload: schemas.RefreshRequest) -> schemas.TokenPair:
    """Renew an operator session.

    The operator row is re-read rather than trusted from the token, so a role change, a
    disablement, or a revocation between issuing and refreshing takes effect here. Without
    that, disabling an operator would leave them working for the refresh token's full
    lifetime, which is the gap the tenant side closed for the same reason.
    """
    principal = decode_platform_token(payload.refresh_token, expected_type="refresh")
    async with platform_session() as session:
        operator = await session.get(PlatformOperator, principal.operator_id)
        if operator is None or operator.status.value != "active":
            raise AuthenticationError("This operator account has been disabled")
        if (
            operator.sessions_revoked_at is not None
            and principal.issued_at is not None
            and principal.issued_at <= operator.sessions_revoked_at
        ):
            raise AuthenticationError(
                "This session was ended by an administrator. Please sign in again."
            )
        access, refresh_token = platform_service.issue_operator_tokens(operator)
    return schemas.TokenPair(
        access_token=access,
        refresh_token=refresh_token,
        expires_in=get_settings().access_token_ttl_seconds,
    )


@router.get("/me", response_model=schemas.PlatformOperatorOut)
async def platform_me(
    principal: PlatformPrincipal = Depends(requires_platform(*_ANY_OPERATOR, mfa_exempt=True)),
    session: AsyncSession = Depends(platform_db_session),
) -> schemas.PlatformOperatorOut:
    """The calling operator's own record.

    `mfa_exempt` for the same reason the enrolment pair is: a session held to the enrolment
    screen has to be able to render it, and rendering it requires knowing whether this
    account already has a factor to replace.
    """
    operator = await session.get(PlatformOperator, principal.operator_id)
    if operator is None:
        raise AuthenticationError("This operator account no longer exists")
    return schemas.PlatformOperatorOut.model_validate(operator)


@router.post("/auth/mfa/enroll", response_model=schemas.MFAEnrolmentStarted)
async def start_platform_mfa_enrolment(
    payload: schemas.MFAEnrolStart | None = None,
    principal: PlatformPrincipal = Depends(requires_platform(*_ANY_OPERATOR, mfa_exempt=True)),
    session: AsyncSession = Depends(platform_db_session),
) -> schemas.MFAEnrolmentStarted:
    """Begin pairing an authenticator for the calling operator.

    Replacing a factor already in force requires `current_code`, exactly as on the tenant
    side. The reasoning is the same and the stakes are higher: without it, a stolen operator
    session is enough to move the second factor for the CareOS console onto another device
    and collect ten fresh recovery codes.
    """
    operator = await session.get(PlatformOperator, principal.operator_id)
    if operator is None:
        raise AuthenticationError("This operator account no longer exists")

    secret, uri, recovery_codes = await platform_service.begin_operator_mfa_enrolment(
        session,
        operator=operator,
        current_code=payload.current_code if payload else None,
    )
    return schemas.MFAEnrolmentStarted(
        secret=secret, otpauth_uri=uri, recovery_codes=recovery_codes
    )


@router.post("/auth/mfa/confirm", response_model=schemas.TokenPair)
async def confirm_platform_mfa_enrolment(
    payload: schemas.MFAConfirm,
    principal: PlatformPrincipal = Depends(requires_platform(*_ANY_OPERATOR, mfa_exempt=True)),
    session: AsyncSession = Depends(platform_db_session),
) -> schemas.TokenPair:
    """Finish enrolment and return a session that satisfies the requirement.

    A fresh pair rather than an upgrade of the one in hand, because a claim inside a signed
    token cannot be changed after the fact — and telling the operator to sign in again would
    fail, since the code they just typed is spent against the replay counter.
    """
    operator = await session.get(PlatformOperator, principal.operator_id)
    if operator is None:
        raise AuthenticationError("This operator account no longer exists")

    await platform_service.confirm_operator_mfa_enrolment(
        session, operator=operator, code=payload.code
    )
    access, refresh_token = platform_service.issue_operator_tokens(operator)
    return schemas.TokenPair(
        access_token=access,
        refresh_token=refresh_token,
        expires_in=get_settings().access_token_ttl_seconds,
    )


@router.get("/agencies", response_model=schemas.FleetOut)
async def list_fleet(
    principal: PlatformPrincipal = Depends(requires_platform(*_ANY_OPERATOR)),
    session: AsyncSession = Depends(platform_db_session),
) -> schemas.FleetOut:
    """Every agency on the platform, worst first.

    Audited. Nothing here is PHI — the role cannot reach any — but "which CareOS employee
    looked at the customer list, and when" is the question this surface exists to make
    answerable, and an access log that records only writes cannot answer it.
    """
    agencies = await platform_service.fleet(session)
    await platform_service.record_platform_audit(
        session,
        actor_operator_id=principal.operator_id,
        action=PlatformAuditAction.fleet_viewed,
        details={"agencies_returned": len(agencies)},
    )
    return schemas.FleetOut(
        summary=schemas.FleetSummaryOut(
            agencies_total=len(agencies),
            agencies_suspended=sum(1 for a in agencies if a.status == "suspended"),
            agencies_with_rejected_evv=sum(1 for a in agencies if a.evv_rejected > 0),
            # "Stalled" is a queue that exists and has not moved, which a count alone cannot
            # express — one pending record from Tuesday and ten from this minute are the same
            # number and different problems.
            agencies_with_stalled_evv=sum(
                1 for a in agencies if a.evv_oldest_pending_at is not None
            ),
            agencies_with_critical_exceptions=sum(
                1 for a in agencies if a.exceptions_open_critical > 0
            ),
            open_critical_exceptions=sum(a.exceptions_open_critical for a in agencies),
        ),
        agencies=[_to_health_out(a) for a in agencies],
    )


@router.get("/agencies/{agency_id}", response_model=schemas.AgencyHealthOut)
async def get_agency_health(
    agency_id: uuid.UUID,
    principal: PlatformPrincipal = Depends(requires_platform(*_ANY_OPERATOR)),
    session: AsyncSession = Depends(platform_db_session),
) -> schemas.AgencyHealthOut:
    """One agency's operational detail. Audited against that agency."""
    health = await platform_service.agency_health(session, agency_id=agency_id)
    await platform_service.record_platform_audit(
        session,
        actor_operator_id=principal.operator_id,
        action=PlatformAuditAction.agency_health_viewed,
        subject_agency_id=agency_id,
    )
    return _to_health_out(health)


@router.post("/agencies/{agency_id}/suspend", response_model=schemas.AgencyHealthOut)
async def suspend_agency(
    agency_id: uuid.UUID,
    payload: schemas.SuspendAgencyRequest,
    principal: PlatformPrincipal = Depends(
        requires_platform(PlatformRole.platform_admin)
    ),
    session: AsyncSession = Depends(platform_db_session),
) -> schemas.AgencyHealthOut:
    """Take an agency offline: nobody in it can sign in, and tokens already issued stop working.

    `platform_admin` only. It is the most consequential action in the system — it stops
    caregivers clocking in, which for a Medicaid-billed visit means an unpaid shift and a
    compliance exception — so the role that reads the fleet all day is deliberately not the
    role that can do it.

    Idempotent by refusal rather than by key: a second suspension of an already-suspended
    agency is a 409, so a double-submitted form cannot produce two audit rows claiming two
    separate suspensions. See `platform_service.suspend_agency` for why no `Idempotency-Key`.
    """
    return _to_health_out(
        await platform_service.suspend_agency(
            session, actor=principal, agency_id=agency_id, reason=payload.reason
        )
    )


@router.post("/agencies/{agency_id}/reinstate", response_model=schemas.AgencyHealthOut)
async def reinstate_agency(
    agency_id: uuid.UUID,
    payload: schemas.ReinstateAgencyRequest,
    principal: PlatformPrincipal = Depends(
        requires_platform(PlatformRole.platform_admin)
    ),
    session: AsyncSession = Depends(platform_db_session),
) -> schemas.AgencyHealthOut:
    """Return a suspended agency to service. A note is required and recorded in both trails."""
    return _to_health_out(
        await platform_service.reinstate_agency(
            session, actor=principal, agency_id=agency_id, note=payload.note
        )
    )


@router.get("/operators", response_model=list[schemas.PlatformOperatorOut])
async def list_operators(
    _principal: PlatformPrincipal = Depends(requires_platform(*_ANY_OPERATOR)),
    session: AsyncSession = Depends(platform_db_session),
) -> list[schemas.PlatformOperatorOut]:
    """Who can operate the platform.

    Readable by both roles, deliberately. Knowing who holds this access is the first thing an
    access review asks, and restricting the list to the people who can change it makes the
    review depend on the reviewer being one of them.
    """
    operators = await platform_service.list_operators(session)
    return [schemas.PlatformOperatorOut.model_validate(o) for o in operators]


@router.post(
    "/operators",
    response_model=schemas.PlatformOperatorOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_operator(
    payload: schemas.PlatformOperatorCreate,
    principal: PlatformPrincipal = Depends(requires_platform(PlatformRole.platform_admin)),
    session: AsyncSession = Depends(platform_db_session),
) -> schemas.PlatformOperatorOut:
    """Add a CareOS operator.

    The bootstrap script (`python -m careos.scripts.create_platform_operator`) creates the
    first one, because there is nobody to authenticate as before that. Everyone after them
    comes through here, so the creation has an actor.
    """
    operator = await platform_service.create_operator(
        session,
        actor=principal,
        email=payload.email,
        display_name=payload.display_name,
        role=payload.role,
        initial_password=payload.initial_password,
    )
    return schemas.PlatformOperatorOut.model_validate(operator)


@router.post("/operators/{operator_id}/disable", response_model=schemas.PlatformOperatorOut)
async def disable_operator(
    operator_id: uuid.UUID,
    payload: schemas.PlatformOperatorDisable,
    principal: PlatformPrincipal = Depends(requires_platform(PlatformRole.platform_admin)),
    session: AsyncSession = Depends(platform_db_session),
) -> schemas.PlatformOperatorOut:
    """Offboard a CareOS operator: stop them signing in, and end the sessions they hold."""
    operator = await platform_service.set_operator_status(
        session, actor=principal, operator_id=operator_id, active=False, reason=payload.reason
    )
    return schemas.PlatformOperatorOut.model_validate(operator)


@router.post("/operators/{operator_id}/enable", response_model=schemas.PlatformOperatorOut)
async def enable_operator(
    operator_id: uuid.UUID,
    principal: PlatformPrincipal = Depends(requires_platform(PlatformRole.platform_admin)),
    session: AsyncSession = Depends(platform_db_session),
) -> schemas.PlatformOperatorOut:
    """Return a disabled operator to service.

    The revocation watermark is deliberately left where it is, for the same reason as the
    tenant side: clearing it would revive every token issued before the disablement.
    """
    operator = await platform_service.set_operator_status(
        session, actor=principal, operator_id=operator_id, active=True, reason=None
    )
    return schemas.PlatformOperatorOut.model_validate(operator)


@router.get("/audit", response_model=list[schemas.PlatformAuditEntryOut])
async def platform_audit(
    limit: int = 100,
    _principal: PlatformPrincipal = Depends(requires_platform(*_ANY_OPERATOR)),
    session: AsyncSession = Depends(platform_db_session),
) -> list[schemas.PlatformAuditEntryOut]:
    """What CareOS operators have done and looked at, newest first.

    Deliberately readable by `platform_support` as well as `platform_admin`. An access log
    that only the people who can act on the system may read is one nobody independent ever
    checks.
    """
    rows = await platform_service.recent_platform_audit(session, limit=min(max(limit, 1), 500))
    return [
        schemas.PlatformAuditEntryOut(
            id=entry.id,
            action=entry.action,
            actor_display_name=actor_name,
            subject_agency_id=entry.subject_agency_id,
            subject_agency_name=agency_name,
            subject_operator_id=entry.subject_operator_id,
            details=entry.details,
            source_ip=entry.source_ip,
            occurred_at=entry.occurred_at,
        )
        for entry, actor_name, agency_name in rows
    ]
