"""Role-based access control, enforced at the API layer.

`08_Security_Architecture.md` Section 1 requires that every endpoint declare its minimum
required role(s) and that a shared mechanism — not per-endpoint ad hoc checks — enforces
them. Two pieces implement that:

* :func:`requires` builds the dependency a route declares its roles with.
* :func:`assert_all_routes_declare_access` runs at application startup and refuses to boot
  if any route declares neither a role requirement nor an explicit :func:`public` opt-out.

The second is the important one. A missing `if role != ...` check is invisible in review;
a route that forgets to declare its access rules here cannot start the server.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.routing import APIRoute

from careos.core.errors import AuthenticationError, PermissionDeniedError
from careos.core.security import Principal
from careos.modules.agency.models import Role

#: Attribute stamped on dependency callables so startup validation can find them.
_ROLES_ATTR = "_careos_required_roles"
_PUBLIC_ATTR = "_careos_public_route"

#: Read-only across the whole tenant, for compliance review
#: (`08_Security_Architecture.md` Section 1). Enforced by rejecting mutating methods.
READ_ONLY_ROLES: frozenset[Role] = frozenset({Role.auditor})

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_principal(request: Request) -> Principal:
    """Pull the Principal the auth middleware attached to this request."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise AuthenticationError("Authentication required")
    return principal


def requires(*roles: Role) -> Callable[..., Principal]:
    """Declare the roles permitted to call a route.

    Usage::

        @router.post("/clients", dependencies=[Depends(requires(Role.owner_admin,
                                                                Role.scheduler))])
    """
    if not roles:
        raise ValueError("requires() needs at least one role; use public() for open routes")
    allowed = frozenset(roles)

    def _dependency(request: Request) -> Principal:
        principal = get_principal(request)
        if principal.role not in allowed:
            raise PermissionDeniedError(
                "Your role is not permitted to perform this action",
                details={"required_roles": sorted(r.value for r in allowed)},
            )
        # The auditor role is read-only tenant-wide. Rather than trusting every route that
        # includes it to also be a GET, reject mutating methods centrally.
        if principal.role in READ_ONLY_ROLES and request.method not in _SAFE_METHODS:
            raise PermissionDeniedError(
                "The auditor role is read-only",
                details={"method": request.method},
            )
        return principal

    setattr(_dependency, _ROLES_ATTR, allowed)
    return _dependency


def public() -> Callable[..., None]:
    """Mark a route as deliberately unauthenticated (login, refresh, health, webhooks).

    An explicit marker rather than an absence, so that "no auth" is always a decision
    someone wrote down and a reviewer can grep for.
    """

    def _dependency() -> None:
        return None

    setattr(_dependency, _PUBLIC_ATTR, True)
    return _dependency


@dataclass(frozen=True, slots=True)
class _RouteSpec:
    """The three things access validation needs, normalized across FastAPI route shapes."""

    path: str
    methods: frozenset[str]
    dependant: Any


def _iter_route_specs(app: FastAPI) -> Iterator[_RouteSpec]:
    """Yield every registered API route, including those inside included routers.

    FastAPI does not present a stable flat list. Depending on version, `app.routes` holds
    either `APIRoute` objects directly, or wrapper objects for included routers that expose
    their contents through `effective_route_contexts()`. Both are handled here.

    Getting this wrong is not a cosmetic problem: a traversal that silently misses routes
    makes :func:`assert_all_routes_declare_access` pass vacuously, which is worse than not
    having the check at all. :func:`assert_route_discovery_is_working` guards that.
    """
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield _RouteSpec(route.path, frozenset(route.methods or ()), route.dependant)
            continue

        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):
            for ctx in contexts():
                dependant = getattr(ctx, "dependant", None)
                if dependant is None:
                    continue
                yield _RouteSpec(
                    getattr(ctx, "path", "<unknown>"),
                    frozenset(getattr(ctx, "methods", ()) or ()),
                    dependant,
                )


def _declared_roles(spec: _RouteSpec) -> frozenset[Role] | None:
    """Roles declared on a route, or None if it declares nothing."""
    for dependency in spec.dependant.dependencies:
        call = dependency.call
        if call is None:
            continue
        roles: frozenset[Role] | None = getattr(call, _ROLES_ATTR, None)
        if roles is not None:
            return roles
        if getattr(call, _PUBLIC_ATTR, False):
            return frozenset()
    return None


def assert_route_discovery_is_working(app: FastAPI, *, minimum: int = 1) -> None:
    """Assert route traversal actually found routes.

    Called before the access check so that a FastAPI upgrade changing the internal route
    layout surfaces as a loud startup failure rather than an access check that quietly
    inspects nothing.
    """
    found = sum(1 for _ in _iter_route_specs(app))
    if found < minimum:
        raise RuntimeError(
            f"Route discovery found {found} routes, expected at least {minimum}. The "
            "FastAPI route layout has probably changed — fix _iter_route_specs before "
            "trusting any access check built on it."
        )


def assert_all_routes_declare_access(app: FastAPI) -> None:
    """Refuse to start if any route is missing an access declaration."""
    assert_route_discovery_is_working(app)
    undeclared = sorted(
        f"{sorted(spec.methods)} {spec.path}"
        for spec in _iter_route_specs(app)
        if _declared_roles(spec) is None
    )
    if undeclared:
        raise RuntimeError(
            "Routes missing an access declaration: "
            f"{undeclared}. Every route must declare Depends(requires(...)) or "
            "Depends(public()) — see 08_Security_Architecture.md Section 1."
        )


def route_access_map(app: FastAPI) -> dict[str, list[str]]:
    """Report each route's permitted roles, keyed ``"METHOD /path"``.

    Doubles as SOC 2 control evidence (`08_Security_Architecture.md` Section 9) and as the
    fixture the RBAC tests assert against.
    """
    access: dict[str, list[str]] = {}
    for spec in _iter_route_specs(app):
        roles = _declared_roles(spec)
        if roles is None:
            continue
        value = sorted(r.value for r in roles) if roles else ["*public*"]
        for method in sorted(spec.methods):
            access[f"{method} {spec.path}"] = value
    return access


__all__ = [
    "Depends",
    "assert_all_routes_declare_access",
    "assert_route_discovery_is_working",
    "get_principal",
    "public",
    "requires",
    "route_access_map",
]
