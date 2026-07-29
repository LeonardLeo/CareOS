"""Agency provisioning and authentication.

The two operations that legitimately precede knowing a tenant live here, and they are the
only callers of `privileged_session()`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core.audit import AuditAction, record_audit
from careos.core.crypto import encrypt_field
from careos.core.errors import AuthenticationError, ConflictError
from careos.core.security import Principal, create_token, hash_password, verify_password
from careos.db.session import tenant_session
from careos.modules.agency.models import Agency, AppUser, Role, UserStatus
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
        raise AuthenticationError("This account is not active")
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
    access = create_token(
        user_id=user.id,
        agency_id=user.agency_id,
        role=user.role,
        token_type="access",
        caregiver_id=caregiver_id,
    )
    refresh = create_token(
        user_id=user.id,
        agency_id=user.agency_id,
        role=user.role,
        token_type="refresh",
        caregiver_id=caregiver_id,
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
