"""FastAPI dependencies: authentication and the tenant-scoped session."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core.errors import AuthenticationError
from careos.core.rbac import get_principal
from careos.core.security import Principal, decode_token
from careos.db.session import tenant_session


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
    request.state.principal = principal
    return principal


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
