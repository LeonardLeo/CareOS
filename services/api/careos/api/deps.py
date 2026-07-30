"""FastAPI dependencies: authentication and the tenant-scoped session."""

from __future__ import annotations

from collections.abc import AsyncIterator

import structlog
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core.errors import AuthenticationError
from careos.core.rbac import get_principal
from careos.core.security import Principal, decode_token
from careos.db.session import begin_tenant_session, tenant_session
from careos.modules.agency.models import AppUser

logger = structlog.get_logger(__name__)


async def authenticate(request: Request) -> Principal | None:
    """Verify the bearer token, if present, and stash the Principal on the request.

    Returns None rather than raising for unauthenticated requests: whether authentication
    is *required* is the route's declaration to make (`requires()` versus `public()`), not
    this function's.

    Signature verification only — deliberately no database access. The revocation check is
    `enforce_session_revocation`, called separately so that rate limiting can run in between:
    an unauthenticated flood should be refused by the limiter before it costs a query per
    request, which is exactly what an attacker would aim for otherwise.
    """
    header = request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError("Authorization header must be a Bearer token")

    principal = decode_token(token, expected_type="access")
    request.state.principal = principal
    return principal


async def enforce_session_revocation(principal: Principal) -> None:
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

    **This deliberately does not commit.** FastAPI runs a `yield` dependency's teardown after
    the response has been sent, so committing here answered the client before the write was
    durable — and left a failed commit with no status code to be reported in. The session is
    published on `request.state.unit_of_work` and `careos.main` commits it in the middleware,
    which still holds the response. Measured, not assumed: with the commit here the client
    saw 200 in 3 ms and could not read its own write for another 300 ms.

    The rollback stays here, because the exception path unwinds through this teardown before
    any response exists — so a handler that raises has its transaction discarded before the
    middleware ever sees it, and the middleware's "still in a transaction?" test is then
    exactly "did this request succeed?".
    """
    principal: Principal | None = getattr(request.state, "principal", None)
    session = await begin_tenant_session(principal.agency_id if principal else None)
    # Marks this session as the one the middleware is responsible for committing. Also what
    # lets a test make *this* commit fail without touching the session the revocation check
    # opens on the way in.
    session.info["careos_request_unit_of_work"] = True
    request.state.unit_of_work = session
    try:
        yield session
    except BaseException:
        await session.rollback()
        raise
    finally:
        request.state.unit_of_work = None
        if session.in_transaction():
            # The middleware commits every successful request, so reaching here with work
            # still pending means the response never went through it. Discard rather than
            # commit — a write nobody was told about is safer than one nobody checked — and
            # say so, because it means the two halves of this have come apart.
            logger.error(
                "request.uncommitted_transaction_discarded",
                path=request.url.path,
                method=request.method,
            )
            await session.rollback()
        await session.close()


async def current_principal(request: Request) -> Principal:
    return get_principal(request)


__all__ = [
    "Depends",
    "authenticate",
    "current_principal",
    "db_session",
    "enforce_session_revocation",
]
