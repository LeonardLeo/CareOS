"""FastAPI dependencies: authentication and the tenant-scoped session."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core.errors import AuthenticationError
from careos.core.rbac import get_principal
from careos.core.security import Principal, decode_token
from careos.db.session import tenant_session
from careos.modules.agency.models import AppUser


async def authenticate(request: Request) -> Principal | None:
    """Resolve the bearer token, if present, and stash the Principal on the request.

    Returns None rather than raising for unauthenticated requests: whether authentication
    is *required* is the route's declaration to make (`requires()` versus `public()`), not
    this function's.
    """
    header = request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError("Authorization header must be a Bearer token")

    principal = decode_token(token, expected_type="access")
    await _assert_session_not_revoked(principal)
    request.state.principal = principal
    return principal


async def _assert_session_not_revoked(principal: Principal) -> None:
    """Refuse a token issued before the user's sessions were revoked.

    This is the server half of the remote-wipe requirement in
    `08_Security_Architecture.md` Section 6. The caregiver app clears its cached client names
    and addresses whenever the API rejects its token, so making the API reject it is what
    actually removes PHI from a terminated caregiver's phone.

    It costs one small query per authenticated request, which is a real price and a deliberate
    one: the requirement is "immediately", and any cache would define a window in which a
    terminated caregiver still holds valid access. Redis is already in the compose stack and
    unused — a short-TTL cache there is the obvious next step if this shows up in latency, and
    would need its invalidation wired to the revoke endpoint rather than left to expiry.

    Read through a tenant session, not the privileged one: the token already establishes the
    agency, so there is no reason to widen `careos_auth`'s reach for this.
    """
    if principal.issued_at is None:
        # decode_token requires `iat`, so this is unreachable via a real token. Refusing
        # rather than skipping keeps the failure closed if that ever stops being true.
        raise AuthenticationError("Token is missing an issued-at claim")

    async with tenant_session(principal.agency_id) as session:
        row = (
            await session.execute(
                select(AppUser.sessions_revoked_at).where(AppUser.id == principal.user_id)
            )
        ).first()

    if row is None:
        # The user was deleted, or RLS hid them because the token names an agency they are not
        # in. Either way the token should no longer work.
        raise AuthenticationError("This account is no longer active")

    revoked_at = row[0]
    if revoked_at is not None and principal.issued_at <= revoked_at:
        # Both sides carry sub-second precision — `issued_at` comes from the `iat_us` claim
        # rather than the whole-second `iat` — so this refuses every token minted before the
        # revocation and admits the re-login that comes after it. An earlier version compared
        # against `iat` and locked users out of signing back in for up to a second.
        raise AuthenticationError(
            "This session was ended by an administrator. Please sign in again."
        )


async def db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A session scoped to the caller's tenant for the life of the request.

    The tenant comes from the verified token via `Principal`, never from the request body
    or query string (`05_API_Specification.md` Section 1). An unauthenticated request gets a
    session with no tenant set, which RLS renders unable to read any tenant-scoped row.
    """
    principal: Principal | None = getattr(request.state, "principal", None)
    async with tenant_session(principal.agency_id if principal else None) as session:
        yield session


async def current_principal(request: Request) -> Principal:
    return get_principal(request)


__all__ = ["Depends", "authenticate", "current_principal", "db_session"]
