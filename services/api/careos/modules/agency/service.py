"""Agency provisioning and authentication.

The two operations that legitimately precede knowing a tenant live here, and they are the
only callers of `privileged_session()`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core import mfa
from careos.core.audit import AuditAction, record_audit
from careos.core.crypto import decrypt_field, encrypt_field
from careos.core.errors import (
    AccountInactiveError,
    AuthenticationError,
    ConflictError,
    MFAInvalidCodeError,
    MFARequiredError,
    PermissionDeniedError,
    ValidationError,
)
from careos.core.security import Principal, create_token, hash_password, verify_password
from careos.db.session import tenant_session
from careos.modules.agency.models import (
    MFA_REQUIRED_ROLES,
    Agency,
    AppUser,
    Role,
    UserStatus,
)
from careos.modules.credentialing.models import Caregiver


async def create_agency(
    session: AsyncSession,
    *,
    legal_name: str,
    tax_id: str | None,
    service_states: list[str],
    service_lines: list[str],
    accepted_payer_types: list[str],
    owner_email: str,
    owner_password: str,
) -> tuple[Agency, AppUser]:
    """Provision a new tenant and its first owner/admin user (US-1.1.1).

    Runs on the privileged session because the tenant does not exist yet, so there is no
    `agency_id` for RLS to scope to. Agency and owner are created in one transaction: a
    tenant with no way to log into it would be unusable and invisible.
    """
    existing = (
        await session.execute(select(AppUser.id).where(AppUser.email == owner_email))
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("A user with this email address already exists")

    agency = Agency(
        legal_name=legal_name,
        tax_id_encrypted=encrypt_field(tax_id),
        service_states=service_states,
        service_lines=service_lines,
        accepted_payer_types=accepted_payer_types,
    )
    session.add(agency)
    await session.flush()

    owner = AppUser(
        agency_id=agency.id,
        role=Role.owner_admin,
        email=owner_email,
        password_hash=hash_password(owner_password),
        status=UserStatus.active,
    )
    session.add(owner)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("A user with this email address already exists") from exc

    # The owner is the actor for their own agency's creation — there is no prior user to
    # attribute it to, and an unattributed row would break the audit trail's continuity.
    await record_audit(
        session,
        principal=Principal(user_id=owner.id, agency_id=agency.id, role=Role.owner_admin),
        agency_id=agency.id,
        action=AuditAction.agency_created,
        entity_type="agency",
        entity_id=agency.id,
        after_state={"legal_name": legal_name, "service_states": service_states},
    )
    return agency, owner


#: Argon2 hash of an unusable password, verified against when no user matches so that a
#: failed lookup costs the same as a wrong password. Without this, response timing alone
#: reveals which email addresses have accounts.
_DUMMY_HASH = hash_password("no-such-user-timing-equalizer")


async def verify_credentials(session: AsyncSession, *, email: str, password: str) -> AppUser:
    """Resolve an email to a user and verify their password.

    Runs on the privileged session, because resolving an email to a user necessarily crosses
    tenants — the tenant is precisely what we are trying to discover. Everything that can be
    done *after* the tenant is known is deliberately left to the caller, so this privileged
    path stays as narrow as possible.
    """
    user = (
        await session.execute(select(AppUser).where(AppUser.email == email))
    ).scalar_one_or_none()

    # Identical error, and identical work, for "no such user" and "wrong password".
    # Distinguishing them lets an unauthenticated caller enumerate which email addresses
    # have accounts, which for a healthcare product is itself a disclosure.
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise AuthenticationError("Invalid email or password")
    if not user.password_hash or not verify_password(password, user.password_hash):
        raise AuthenticationError("Invalid email or password")
    if user.status is not UserStatus.active:
        # Checked after the password, so this branch is only reachable by someone holding
        # valid credentials — which is what makes saying so safe, and useful.
        raise AccountInactiveError(
            "This account has been disabled. Contact your agency administrator."
        )
    return user


async def complete_login(
    session: AsyncSession, *, user_id: uuid.UUID, agency_id: uuid.UUID, role: Role
) -> uuid.UUID | None:
    """Record the successful login and resolve the caller's caregiver id, if any.

    Runs on a normal tenant-scoped session now that the tenant is known, so the `caregiver`
    table stays out of the privileged role's reach.
    """
    caregiver_id = (
        await session.execute(select(Caregiver.id).where(Caregiver.app_user_id == user_id))
    ).scalar_one_or_none()

    await record_audit(
        session,
        principal=Principal(user_id=user_id, agency_id=agency_id, role=role),
        agency_id=agency_id,
        action=AuditAction.user_login_succeeded,
        entity_type="app_user",
        entity_id=user_id,
    )
    return caregiver_id


async def record_failed_login(session: AsyncSession, *, email: str) -> None:
    """Audit a failed login attempt against a known account.

    Best-effort: an attempt for an address with no account has no tenant to attribute to and
    is therefore not recorded here.
    """
    user = (
        await session.execute(select(AppUser).where(AppUser.email == email))
    ).scalar_one_or_none()
    if user is None:
        return
    async with tenant_session(user.agency_id) as tenant:
        await record_audit(
            tenant,
            principal=None,
            agency_id=user.agency_id,
            action=AuditAction.user_login_failed,
            entity_type="app_user",
            entity_id=user.id,
        )


def issue_tokens(user: AppUser, caregiver_id: uuid.UUID | None) -> tuple[str, str]:
    """Mint a fresh pair for a user whose identity is already established (the refresh path).

    The MFA state is re-derived from the user rather than carried over from the presented
    token. Both directions matter: without this, a pending session could be refreshed into a
    satisfied one — laundering an unenrolled privileged user into full access through an
    endpoint that never asks for a code — and a user who enrolled on another device would stay
    locked to the enrolment endpoints until their refresh token expired.
    """
    mfa_satisfied = user.mfa_enrolled or user.role not in MFA_REQUIRED_ROLES
    access = create_token(
        user_id=user.id,
        agency_id=user.agency_id,
        role=user.role,
        token_type="access",
        caregiver_id=caregiver_id,
        mfa_satisfied=mfa_satisfied,
    )
    refresh = create_token(
        user_id=user.id,
        agency_id=user.agency_id,
        role=user.role,
        token_type="refresh",
        caregiver_id=caregiver_id,
        mfa_satisfied=mfa_satisfied,
    )
    return access, refresh


async def invite_user(
    session: AsyncSession,
    *,
    principal: Principal,
    email: str,
    role: Role,
    phone: str | None,
    initial_password: str,
) -> AppUser:
    """Invite a user into the caller's agency (US-1.1.2)."""
    user = AppUser(
        agency_id=principal.agency_id,
        role=role,
        email=email,
        phone=phone,
        password_hash=hash_password(initial_password),
        status=UserStatus.active,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("A user with this email address already exists") from exc

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.user_invited,
        entity_type="app_user",
        entity_id=user.id,
        after_state={"email": email, "role": role.value},
    )
    return user


async def revoke_sessions(
    session: AsyncSession,
    *,
    principal: Principal,
    user: AppUser,
    reason: str,
) -> AppUser:
    """Cut off every outstanding session for `user`, effective immediately.

    The single point of truth for revocation, shared by the explicit admin action and by
    caregiver termination. Having one implementation is the point: `08_Security_Architecture.md`
    Section 6 requires that offboarding actually removes access, and two copies of this would
    eventually disagree about whether it also writes an audit row.

    The watermark is set from the database clock rather than the application's. A slow or
    skewed app server could otherwise write a timestamp behind tokens it had just issued,
    leaving them valid — the failure would be silent and would look like revocation working.

    `clock_timestamp()`, not `now()`: `now()` is the transaction's start time, so in a
    transaction that does other work first the watermark would sit measurably in the past and
    tokens minted in between would survive. This leaves one narrow race — a login committing
    between this read and this transaction's commit — bounded by the length of that
    transaction. Closing it entirely needs the login path to serialize against the user row,
    which is not worth the contention for a window of milliseconds.
    """
    revoked_at = (await session.execute(select(func.clock_timestamp()))).scalar_one()
    before = {
        "sessions_revoked_at": (
            user.sessions_revoked_at.isoformat() if user.sessions_revoked_at else None
        )
    }
    user.sessions_revoked_at = revoked_at
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.user_sessions_revoked,
        entity_type="app_user",
        entity_id=user.id,
        before_state=before,
        after_state={"sessions_revoked_at": revoked_at.isoformat(), "reason": reason},
    )
    return user


async def _other_active_owner_admins(session: AsyncSession, *, excluding: uuid.UUID) -> int:
    """How many usable owner/admins the agency would still have without this one."""
    return (
        await session.execute(
            select(func.count())
            .select_from(AppUser)
            .where(
                AppUser.role == Role.owner_admin,
                AppUser.status == UserStatus.active,
                AppUser.id != excluding,
            )
        )
    ).scalar_one()


async def disable_user(
    session: AsyncSession,
    *,
    principal: Principal,
    user: AppUser,
    reason: str,
) -> AppUser:
    """Disable an account and cut off its sessions, in one transaction.

    Distinct from revoking sessions, and the distinction is the whole point. Revocation
    invalidates the tokens a user is holding; it does not stop them signing in again a second
    later with the password they still know. That is correct for a lost phone and wrong for
    everything else — before this, terminating a caregiver revoked their sessions and left them
    able to log straight back in, which is an offboarding feature that produces a record saying
    access was removed while it was not.

    Disabling closes both doors: `status` stops the login path issuing new tokens and stops the
    refresh path renewing old ones, and the revocation watermark kills the tokens already out
    there. Doing only the first would leave a disabled account working for the remaining life of
    its access token; doing only the second is the gap described above.

    Deliberately not deletion. An agency needs the account to keep existing — audit rows point
    at it, a rehire is common in home care, and a deleted user makes historical activity
    unattributable.
    """
    if user.id == principal.user_id:
        raise PermissionDeniedError(
            "You cannot disable your own account. To sign yourself out everywhere, revoke "
            "your sessions instead — that is reversible by signing back in."
        )
    if (
        user.role is Role.owner_admin
        and user.status is UserStatus.active
        and await _other_active_owner_admins(session, excluding=user.id) == 0
    ):
        # The same reasoning as the self-demotion guard on role changes: an agency with no
        # enabled owner/admin cannot invite one, and recovering needs support to reach into
        # the database. Refusing here is cheaper than that conversation.
        raise ConflictError(
            "This is the agency's only enabled owner/admin. Promote or enable another "
            "owner/admin first, or the agency would be left with nobody able to administer it."
        )

    before = {"status": user.status.value, "disabled_reason": user.disabled_reason}
    user.status = UserStatus.suspended
    user.disabled_reason = reason
    await session.flush()

    # Sessions go too, and through the shared implementation rather than a second copy of the
    # watermark logic. This writes its own audit row, so the trail shows both facts: the
    # account was disabled, and the tokens outstanding at that moment stopped working.
    await revoke_sessions(session, principal=principal, user=user, reason=f"disabled: {reason}")

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.user_disabled,
        entity_type="app_user",
        entity_id=user.id,
        before_state=before,
        after_state={"status": user.status.value, "disabled_reason": reason},
    )
    return user


async def enable_user(
    session: AsyncSession,
    *,
    principal: Principal,
    user: AppUser,
) -> AppUser:
    """Return a disabled account to service.

    The revocation watermark is deliberately left where it is. Clearing it would resurrect
    every token issued before the disablement — including, in the case this exists for, the one
    on a phone that was handed back. The user signs in again and gets tokens minted after the
    watermark, which is the same path a normal password change leaves them on.
    """
    before = {"status": user.status.value, "disabled_reason": user.disabled_reason}
    user.status = UserStatus.active
    user.disabled_reason = None
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.user_enabled,
        entity_type="app_user",
        entity_id=user.id,
        before_state=before,
        after_state={"status": user.status.value},
    )
    return user


async def begin_mfa_enrolment(
    session: AsyncSession,
    *,
    principal: Principal,
    user: AppUser,
    current_code: str | None = None,
) -> tuple[str, str, list[str]]:
    """Issue a TOTP secret and recovery codes. Returns (secret, otpauth URI, recovery codes).

    **`mfa_enrolled` is deliberately not set here.** Enrolment is not finished until the user
    has produced a code from the secret, and marking them enrolled on issue would lock out
    anyone who closed the tab before scanning — with no way back in, since the requirement they
    would then fail is the one that gates every endpoint.

    Re-enrolling replaces the secret and the recovery codes, and **an account that is already
    enrolled must prove the factor it currently has**. Without that check a session token is
    enough to move somebody's MFA onto another device: the thief enrols their own
    authenticator, receives ten fresh recovery codes, and now holds the second factor that was
    supposed to contain them. Verified against the running API before it was fixed — a bare
    session replaced the secret and returned new codes.

    The proof goes through the same path a login does, so a TOTP code is spent against the
    replay counter and a recovery code is consumed. Re-enrolling therefore costs one of them,
    which is correct: it is an authentication.
    """
    if user.mfa_enrolled:
        assert_mfa_satisfied(user, code=current_code)

    secret = mfa.generate_secret()
    recovery_codes = mfa.generate_recovery_codes()

    user.mfa_secret_encrypted = encrypt_field(secret)
    # Hashed with the password hasher, because each of these is a credential that skips the
    # second factor entirely. Normalized first so the stored hash matches what a person types.
    user.mfa_recovery_hashes = [
        hash_password(mfa.normalize_recovery_code(code)) for code in recovery_codes
    ]
    user.mfa_last_counter = None
    user.mfa_enrolled = False
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.mfa_enrolment_started,
        entity_type="app_user",
        entity_id=user.id,
        # No secret, no codes. An audit log is read by more people than this response is.
        after_state={"recovery_codes_issued": len(recovery_codes)},
    )
    return secret, mfa.provisioning_uri(secret, account=user.email), recovery_codes


async def confirm_mfa_enrolment(
    session: AsyncSession, *, principal: Principal, user: AppUser, code: str
) -> AppUser:
    """Finish enrolment by proving the user can produce a code."""
    secret = decrypt_field(user.mfa_secret_encrypted)
    if secret is None:
        raise ValidationError(
            "Start enrolment before confirming it.", details={"user_id": str(user.id)}
        )

    counter = mfa.verify_code(secret, code, last_counter=user.mfa_last_counter)
    if counter is None:
        raise MFAInvalidCodeError("That code is not valid. Check your authenticator app's clock.")

    user.mfa_enrolled = True
    user.mfa_last_counter = counter
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.mfa_enrolled,
        entity_type="app_user",
        entity_id=user.id,
        after_state={"mfa_enrolled": True},
    )
    return user


def _consume_recovery_code(user: AppUser, code: str) -> bool:
    """Spend one recovery code, or return False.

    Single-use is the whole point: a code that still works after being used is a permanent
    second password written on a piece of paper. Verified against every stored hash rather
    than a lookup, because they are hashed — which is why they cost a linear scan of ten.
    """
    supplied = mfa.normalize_recovery_code(code)
    remaining = list(user.mfa_recovery_hashes or [])
    for stored in remaining:
        if verify_password(supplied, stored):
            remaining.remove(stored)
            # Reassigned rather than mutated in place: SQLAlchemy does not track mutation of a
            # plain JSONB list, so `remaining.remove(...)` alone would leave the code usable
            # forever and nothing would look wrong.
            user.mfa_recovery_hashes = remaining
            return True
    return False


def assert_mfa_satisfied(user: AppUser, *, code: str | None) -> None:
    """Check the second factor at login, or raise.

    Called after the password verifies, so every branch here is reachable only by someone who
    already holds valid credentials — which is what makes saying "the code is wrong" safe.
    """
    if not user.mfa_enrolled:
        return

    secret = decrypt_field(user.mfa_secret_encrypted)
    if secret is None:
        # Enrolled with no secret should be impossible. Failing closed rather than waving it
        # through: the alternative is that a corrupted row silently downgrades an account to
        # single-factor.
        raise MFARequiredError("Multi-factor authentication is not usable on this account.")

    if not code:
        raise MFARequiredError("Enter the code from your authenticator app.")

    counter = mfa.verify_code(secret, code, last_counter=user.mfa_last_counter)
    if counter is not None:
        user.mfa_last_counter = counter
        return

    if _consume_recovery_code(user, code):
        return

    raise MFAInvalidCodeError("That code is not valid.")
