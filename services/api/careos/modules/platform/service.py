"""Platform operator authentication, fleet reporting, and agency suspension.

Everything here runs on the `careos_platform` pool (`careos.db.session.platform_session`),
which holds no `BYPASSRLS`. What that role can reach is enumerated in migration
`0013_platform_operations`; the short version is one aggregate view, six columns of `agency`,
its own two tables, and `INSERT` on `audit_log`.

**Every query in this module names its columns.** Not style: the `agency` grant is
column-scoped, so `select(Agency)` — which asks for `tax_id_encrypted` among others — is a
runtime permission error rather than a slightly-too-wide read. Writing the columns out is
what keeps the code and the grant describing the same thing, and it means a future column
holding something sensitive is excluded by default instead of by review.

**Every read is audited, not just every write.** `08_Security_Architecture.md` Section 4
requires PHI reads to be recorded because HIPAA's audit-control requirement covers them.
Nothing reachable from here is PHI — that is the point of the grant model — but "which CareOS
employee looked at which customer, and when" is the question this surface exists to be able
to answer, and an access log that only records changes cannot answer it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core import second_factor
from careos.core.audit import AuditAction
from careos.core.context import current_request_id, current_source_ip
from careos.core.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from careos.core.security import (
    PlatformPrincipal,
    create_platform_token,
    hash_password,
    verify_password,
)
from careos.modules.agency.models import Agency, AgencyStatus
from careos.modules.audit.models import AuditLog
from careos.modules.platform.models import (
    PLATFORM_HEALTH_COLUMNS,
    PLATFORM_HEALTH_VIEW,
    PlatformAuditAction,
    PlatformAuditLog,
    PlatformOperator,
    PlatformOperatorStatus,
    PlatformRole,
)

#: Argon2 hash of an unusable password, verified against when no operator matches, so a
#: failed lookup costs the same as a wrong password. Same reasoning as the tenant side:
#: without it, response timing alone reveals which addresses are CareOS staff accounts.
_DUMMY_HASH = hash_password("no-such-operator-timing-equalizer")


# --- Audit ------------------------------------------------------------------------------


async def record_platform_audit(
    session: AsyncSession,
    *,
    actor_operator_id: uuid.UUID | None,
    action: PlatformAuditAction,
    subject_agency_id: uuid.UUID | None = None,
    subject_operator_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> PlatformAuditLog:
    """Append one row to the platform trail, in the caller's open transaction.

    Flushed, never committed, for the same reason `careos.core.audit.record_audit` is: the
    record of an action and the action itself have to land or roll back together, or there is
    a window in which one exists without the other.
    """
    entry = PlatformAuditLog(
        actor_operator_id=actor_operator_id,
        action=action.value,
        subject_agency_id=subject_agency_id,
        subject_operator_id=subject_operator_id,
        details=details or {},
        request_id=current_request_id(),
        source_ip=current_source_ip(),
    )
    session.add(entry)
    await session.flush()
    return entry


# --- Authentication ---------------------------------------------------------------------


async def verify_operator_credentials(
    session: AsyncSession, *, email: str, password: str
) -> PlatformOperator:
    """Resolve an address to an operator and verify their password.

    Identical error and identical work for "no such operator" and "wrong password". The
    disclosure being avoided here is narrower than the tenant one and worth more to an
    attacker: the set of addresses that are CareOS staff accounts is exactly the phishing
    target list for the most privileged principal in the system.
    """
    operator = (
        await session.execute(
            select(PlatformOperator).where(PlatformOperator.email == email.strip().lower())
        )
    ).scalar_one_or_none()

    if operator is None:
        verify_password(password, _DUMMY_HASH)
        raise AuthenticationError("Invalid email or password")
    if not operator.password_hash or not verify_password(password, operator.password_hash):
        raise AuthenticationError("Invalid email or password")
    if operator.status is not PlatformOperatorStatus.active:
        raise AuthenticationError("This operator account has been disabled")
    return operator


def issue_operator_tokens(operator: PlatformOperator) -> tuple[str, str]:
    """Mint an access/refresh pair for an operator whose identity is established.

    `mfa_satisfied` is `operator.mfa_enrolled` and nothing else — no role table, no
    configuration flag. An operator who has not enrolled gets a real session that reaches the
    enrolment endpoints and `/platform/me`, and nothing else, because refusing the login
    outright would make the requirement unsatisfiable: enrolling requires an authenticated
    call made before enrolling.

    Re-derived from the row on every mint, including on refresh, so a pending session cannot
    be laundered into a satisfied one through an endpoint that never asks for a code.
    """
    satisfied = operator.mfa_enrolled
    return (
        create_platform_token(
            operator_id=operator.id,
            role=operator.role,
            token_type="access",
            mfa_satisfied=satisfied,
        ),
        create_platform_token(
            operator_id=operator.id,
            role=operator.role,
            token_type="refresh",
            mfa_satisfied=satisfied,
        ),
    )


async def record_operator_login(
    session: AsyncSession, *, operator: PlatformOperator
) -> None:
    operator.last_login_at = datetime.now(UTC)
    await session.flush()
    await record_platform_audit(
        session,
        actor_operator_id=operator.id,
        action=PlatformAuditAction.operator_login_succeeded,
        subject_operator_id=operator.id,
        details={"role": operator.role.value, "mfa_enrolled": operator.mfa_enrolled},
    )


async def record_failed_operator_login(session: AsyncSession, *, email: str) -> None:
    """Audit a failed attempt against a known operator account.

    Best-effort by design: an attempt against an address with no account has no actor to
    attribute it to, and inventing one would put a fiction in an audit trail. The address
    itself is deliberately not stored for the unknown case — an audit table that accumulates
    every address anyone has ever typed at this form becomes its own disclosure.
    """
    operator = (
        await session.execute(
            select(PlatformOperator.id).where(PlatformOperator.email == email.strip().lower())
        )
    ).scalar_one_or_none()
    if operator is None:
        return
    await record_platform_audit(
        session,
        actor_operator_id=operator,
        action=PlatformAuditAction.operator_login_failed,
        subject_operator_id=operator,
    )


def assert_operator_mfa_satisfied(operator: PlatformOperator, *, code: str | None) -> None:
    """Check the operator's second factor at login, or raise."""
    second_factor.assert_satisfied(operator, code=code)


async def begin_operator_mfa_enrolment(
    session: AsyncSession,
    *,
    operator: PlatformOperator,
    current_code: str | None = None,
) -> tuple[str, str, list[str]]:
    """Issue a TOTP secret and recovery codes for an operator.

    Same rules as the tenant side, through the same implementation: nothing is marked
    enrolled until a code is proved, and replacing a factor that is already in force requires
    proving the one in force. The second is what stops a stolen operator session from moving
    the second factor for the CareOS operator console onto somebody else's phone.
    """
    if operator.mfa_enrolled:
        assert_operator_mfa_satisfied(operator, code=current_code)

    secret, uri, recovery_codes = second_factor.issue(operator, account=operator.email)
    await session.flush()
    await record_platform_audit(
        session,
        actor_operator_id=operator.id,
        action=PlatformAuditAction.operator_mfa_enrolment_started,
        subject_operator_id=operator.id,
        details={"recovery_codes_issued": len(recovery_codes)},
    )
    return secret, uri, recovery_codes


async def confirm_operator_mfa_enrolment(
    session: AsyncSession, *, operator: PlatformOperator, code: str
) -> PlatformOperator:
    second_factor.confirm(operator, code)
    await session.flush()
    await record_platform_audit(
        session,
        actor_operator_id=operator.id,
        action=PlatformAuditAction.operator_mfa_enrolled,
        subject_operator_id=operator.id,
    )
    return operator


# --- Operator administration --------------------------------------------------------------


async def create_operator(
    session: AsyncSession,
    *,
    actor: PlatformPrincipal | None,
    email: str,
    display_name: str,
    role: PlatformRole,
    initial_password: str,
) -> PlatformOperator:
    """Add a CareOS operator account.

    `actor` is None only for the bootstrap script, which runs before any operator exists and
    is the one path that legitimately has no one to attribute the creation to. Every other
    caller is a `platform_admin` acting through the API.
    """
    operator = PlatformOperator(
        email=email.strip().lower(),
        display_name=display_name.strip(),
        role=role,
        password_hash=hash_password(initial_password),
        status=PlatformOperatorStatus.active,
    )
    session.add(operator)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("An operator with this email address already exists") from exc

    await record_platform_audit(
        session,
        actor_operator_id=actor.operator_id if actor else None,
        action=PlatformAuditAction.operator_created,
        subject_operator_id=operator.id,
        details={"email": operator.email, "role": role.value, "bootstrap": actor is None},
    )
    return operator


async def _count_other_active_admins(session: AsyncSession, *, excluding: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(PlatformOperator)
            .where(
                PlatformOperator.role == PlatformRole.platform_admin,
                PlatformOperator.status == PlatformOperatorStatus.active,
                PlatformOperator.id != excluding,
            )
        )
    ).scalar_one()


async def set_operator_status(
    session: AsyncSession,
    *,
    actor: PlatformPrincipal,
    operator_id: uuid.UUID,
    active: bool,
    reason: str | None,
) -> PlatformOperator:
    """Disable or re-enable an operator account, and cut its sessions when disabling.

    The two guards mirror the tenant-side ones and exist for the same reasons. Disabling your
    own account is unrecoverable without database access; disabling the last active
    `platform_admin` leaves CareOS unable to administer its own console, which is a worse
    version of the same problem because there is no second tenant to fall back on.

    Disabling sets the revocation watermark in the same transaction. Status alone would leave
    a departing employee's access token working for the rest of its TTL, and the watermark
    alone would let them sign straight back in — the same two-halves argument as
    `careos.modules.agency.service.disable_user`.
    """
    operator = await session.get(PlatformOperator, operator_id)
    if operator is None:
        raise NotFoundError("Operator not found")

    if not active:
        if operator.id == actor.operator_id:
            raise PermissionDeniedError(
                "You cannot disable your own operator account. Ask another platform "
                "administrator to do it."
            )
        if (
            operator.role is PlatformRole.platform_admin
            and operator.status is PlatformOperatorStatus.active
            and await _count_other_active_admins(session, excluding=operator.id) == 0
        ):
            raise ConflictError(
                "This is the last enabled platform administrator. Enable another one first, "
                "or nobody would be able to administer the CareOS console."
            )

    before = {"status": operator.status.value, "disabled_reason": operator.disabled_reason}
    if active:
        operator.status = PlatformOperatorStatus.active
        operator.disabled_reason = None
    else:
        operator.status = PlatformOperatorStatus.suspended
        operator.disabled_reason = reason
        # From the database clock, not the application's. A skewed app server could write a
        # watermark behind tokens it had just issued, and the failure would look like
        # revocation working.
        operator.sessions_revoked_at = (
            await session.execute(select(func.clock_timestamp()))
        ).scalar_one()
    await session.flush()

    await record_platform_audit(
        session,
        actor_operator_id=actor.operator_id,
        action=(
            PlatformAuditAction.operator_enabled
            if active
            else PlatformAuditAction.operator_disabled
        ),
        subject_operator_id=operator.id,
        details={"before": before, "reason": reason},
    )
    return operator


async def list_operators(session: AsyncSession) -> list[PlatformOperator]:
    return list(
        (
            await session.execute(
                select(PlatformOperator).order_by(PlatformOperator.created_at)
            )
        )
        .scalars()
        .all()
    )


# --- Fleet reporting ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgencyHealth:
    """One row of `platform_agency_health`.

    A frozen dataclass rather than a dict, so a column renamed in the migration and not here
    fails at import of the row rather than rendering an empty cell in the console. The test
    suite additionally compares this field list against the view's actual columns.
    """

    agency_id: uuid.UUID
    legal_name: str
    status: str
    suspended_at: datetime | None
    suspended_reason: str | None
    service_states: list[str]
    service_lines: list[str]
    created_at: datetime
    users_total: int
    users_active: int
    owner_admins_active: int
    users_missing_mfa: int
    caregivers_active: int
    clients_active: int
    visits_next_7d: int
    visits_unfilled_next_7d: int
    evv_pending: int
    evv_transmitted: int
    evv_acknowledged: int
    evv_rejected: int
    evv_oldest_pending_at: datetime | None
    exceptions_open_critical: int
    exceptions_open_warning: int
    exceptions_open_info: int
    credentials_expired: int
    credentials_expiring_30d: int
    last_user_login_at: datetime | None


#: `SELECT <columns> FROM platform_agency_health`, built from the declared column tuple so
#: the projection cannot drift from the dataclass above.
_HEALTH_SELECT = f"SELECT {', '.join(PLATFORM_HEALTH_COLUMNS)} FROM {PLATFORM_HEALTH_VIEW}"


def _to_health(row: Any) -> AgencyHealth:
    return AgencyHealth(**dict(zip(PLATFORM_HEALTH_COLUMNS, row, strict=True)))


async def fleet(session: AsyncSession) -> list[AgencyHealth]:
    """Every agency, worst first.

    Ordered by suspension, then by open critical exceptions, then by rejected EVV records,
    then by the oldest pending transmission. That ordering is the console's whole argument:
    an operator opening this screen is looking for the tenant that needs a phone call, and a
    list sorted by name makes them read four hundred rows to find it.
    """
    rows = await session.execute(
        text(
            f"""
            {_HEALTH_SELECT}
            ORDER BY (status = 'suspended') DESC,
                     exceptions_open_critical DESC,
                     evv_rejected DESC,
                     evv_oldest_pending_at ASC NULLS LAST,
                     legal_name ASC
            """
        )
    )
    return [_to_health(row) for row in rows]


async def agency_health(session: AsyncSession, *, agency_id: uuid.UUID) -> AgencyHealth:
    row = (
        await session.execute(
            text(f"{_HEALTH_SELECT} WHERE agency_id = :agency_id"), {"agency_id": agency_id}
        )
    ).first()
    if row is None:
        raise NotFoundError("Agency not found")
    return _to_health(row)


# --- Suspension -------------------------------------------------------------------------


async def _write_tenant_audit(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    action: AuditAction,
    actor: PlatformPrincipal,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any] | None,
) -> None:
    """Write into the *agency's own* trail that CareOS acted on it.

    `actor_user_id` is null, because the actor is not one of this agency's users and pointing
    the column at one would be false. Who did it travels in `after_state` instead, as an
    operator id and role rather than a name — the agency does not need a CareOS employee's
    identity, and the platform trail has it.

    Uses `careos.modules.audit.models.AuditLog` directly rather than `record_audit`, because
    that helper takes a tenant `Principal` and there is deliberately no way to construct one
    for an operator. The row is otherwise identical, including landing in this transaction.

    **A Core `insert()` rather than `session.add()`, and that is load-bearing.** An ORM insert
    emits `RETURNING occurred_at` to fetch the server default back — which needs `SELECT` on
    that column, and this role deliberately holds no read grant on `audit_log` at all. Rather
    than widening the grant to make the ORM comfortable, the timestamp is supplied explicitly
    from the database clock and nothing is read back. The failure was not theoretical: the
    first version of this raised `permission denied for table audit_log` on the RETURNING.
    """
    await session.execute(
        insert(AuditLog).values(
            id=uuid.uuid4(),
            agency_id=agency_id,
            actor_user_id=None,
            action=action.value,
            entity_type="agency",
            entity_id=agency_id,
            before_state=before_state,
            after_state=after_state,
            is_phi_access=False,
            request_id=current_request_id(),
            source_ip=current_source_ip(),
            occurred_at=func.clock_timestamp(),
        )
    )


async def _agency_status(session: AsyncSession, agency_id: uuid.UUID) -> tuple[str, str | None]:
    row = (
        await session.execute(
            select(Agency.status, Agency.suspended_reason).where(Agency.id == agency_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("Agency not found")
    return row[0], row[1]


async def suspend_agency(
    session: AsyncSession,
    *,
    actor: PlatformPrincipal,
    agency_id: uuid.UUID,
    reason: str,
) -> AgencyHealth:
    """Take a tenant offline. Requires a written reason, and records it in two places.

    No `Idempotency-Key`. `05_API_Specification.md` Section 1 requires one on mutations with
    *external* side effects — EVV transmission, claim submission, background-check initiation
    — and this has none: it sets a column. Replaying it is refused on its merits instead, by
    the `status = 'active'` predicate on the UPDATE, so a double-submitted form produces one
    suspension and one audit row rather than two of each.

    The tenant audit row is written **before** the status changes, and both are in the same
    transaction. Order matters only for legibility; atomicity is what matters, and it means
    an agency can never be suspended without its own trail saying so.
    """
    current_status, _ = await _agency_status(session, agency_id)
    if current_status == AgencyStatus.suspended.value:
        raise ConflictError(
            "This agency is already suspended.",
            details={"agency_id": str(agency_id)},
        )

    suspended_at = (await session.execute(select(func.clock_timestamp()))).scalar_one()
    result = await session.execute(
        update(Agency)
        .where(Agency.id == agency_id, Agency.status == AgencyStatus.active)
        .values(
            status=AgencyStatus.suspended,
            suspended_at=suspended_at,
            suspended_reason=reason,
        )
        .returning(Agency.id)
    )
    if result.first() is None:
        # Another operator suspended it between the read above and this write. Same answer as
        # if they had got there first, which they did.
        raise ConflictError(
            "This agency is already suspended.", details={"agency_id": str(agency_id)}
        )

    await _write_tenant_audit(
        session,
        agency_id=agency_id,
        action=AuditAction.agency_suspended,
        actor=actor,
        before_state={"status": AgencyStatus.active.value},
        after_state={
            "status": AgencyStatus.suspended.value,
            "reason": reason,
            "suspended_by_platform_operator": str(actor.operator_id),
            "platform_role": actor.role.value,
        },
    )
    await record_platform_audit(
        session,
        actor_operator_id=actor.operator_id,
        action=PlatformAuditAction.agency_suspended,
        subject_agency_id=agency_id,
        details={"reason": reason},
    )
    return await agency_health(session, agency_id=agency_id)


async def reinstate_agency(
    session: AsyncSession,
    *,
    actor: PlatformPrincipal,
    agency_id: uuid.UUID,
    note: str,
) -> AgencyHealth:
    """Put a suspended tenant back into service.

    `suspended_at` and `suspended_reason` are cleared, because they describe a suspension
    that is over and leaving them would make the agency's own screen say it is suspended
    while it works. The history is in both audit trails, which is where history belongs.

    A note is required here as well as on the suspension. The asymmetry the tenant-side
    enable/disable pair has — reason to remove access, nothing to restore it — is right when
    an administrator is acting inside their own agency, and wrong when CareOS is acting on a
    customer: "why did we turn this back on" is exactly the question a dispute asks.
    """
    current_status, previous_reason = await _agency_status(session, agency_id)
    if current_status != AgencyStatus.suspended.value:
        raise ConflictError(
            "This agency is not suspended.", details={"agency_id": str(agency_id)}
        )

    result = await session.execute(
        update(Agency)
        .where(Agency.id == agency_id, Agency.status == AgencyStatus.suspended)
        .values(status=AgencyStatus.active, suspended_at=None, suspended_reason=None)
        .returning(Agency.id)
    )
    if result.first() is None:
        raise ConflictError(
            "This agency is not suspended.", details={"agency_id": str(agency_id)}
        )

    await _write_tenant_audit(
        session,
        agency_id=agency_id,
        action=AuditAction.agency_reinstated,
        actor=actor,
        before_state={"status": AgencyStatus.suspended.value, "reason": previous_reason},
        after_state={
            "status": AgencyStatus.active.value,
            "note": note,
            "reinstated_by_platform_operator": str(actor.operator_id),
            "platform_role": actor.role.value,
        },
    )
    await record_platform_audit(
        session,
        actor_operator_id=actor.operator_id,
        action=PlatformAuditAction.agency_reinstated,
        subject_agency_id=agency_id,
        details={"note": note, "previous_reason": previous_reason},
    )
    return await agency_health(session, agency_id=agency_id)


# --- The platform's own access log --------------------------------------------------------


async def recent_platform_audit(
    session: AsyncSession, *, limit: int = 100
) -> list[tuple[PlatformAuditLog, str | None, str | None]]:
    """The platform trail, newest first, with the actor's name and the subject agency's.

    Readable by both platform roles. An access log that only the people who can act on it may
    read is one nobody checks; `platform_support` exists partly to be the pair of eyes on
    what `platform_admin` did.
    """
    rows = await session.execute(
        select(PlatformAuditLog, PlatformOperator.display_name, Agency.legal_name)
        .outerjoin(PlatformOperator, PlatformOperator.id == PlatformAuditLog.actor_operator_id)
        .outerjoin(Agency, Agency.id == PlatformAuditLog.subject_agency_id)
        .order_by(PlatformAuditLog.occurred_at.desc())
        .limit(limit)
    )
    return [(entry, actor, agency) for entry, actor, agency in rows]
