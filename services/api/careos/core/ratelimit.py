"""Rate limiting (`05_API_Specification.md` Section 9).

The spec gives two rules: 100 requests/minute per agency for standard endpoints, and clock-in
and clock-out are **exempt** because throttling a legally time-sensitive action is not an option
— an EVV record that could not be created because a caregiver's agency was busy is a compliance
failure, and refusing it would convert someone else's traffic spike into this caregiver's unpaid
visit.

Two things here go beyond the letter of that section, both deliberately:

* **Pre-authentication limits.** The spec keys everything by agency, but login happens before
  any agency is known, so under a literal reading the one endpoint where an attacker gets
  unlimited attempts is the password form. Session revocation made that worse rather than
  better: it gives an attacker a reason to hammer login after being cut off. Auth endpoints
  therefore get their own tier, keyed by source address, plus a tighter per-account limit
  applied inside the login handler where the email is available.
* **Exemption is a closed list, checked at startup.** Which endpoints are exempt is a security
  decision, and the dangerous direction is a *new* endpoint accidentally landing in the exempt
  set. `assert_rate_limit_paths_exist` fails the boot if a declared path no longer matches a
  real route, so renaming clock-in cannot silently un-exempt it and a typo cannot silently
  exempt nothing.

Token buckets rather than fixed windows. A fixed window lets a caller spend its whole allowance
in the last second of one window and again in the first second of the next — a 2x burst at every
boundary — and the burst arrives precisely when a retrying client has synchronized itself to the
window. A bucket smooths that and yields an honest `Retry-After` for free.
"""

from __future__ import annotations

import enum
import math
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI

import structlog

logger = structlog.get_logger(__name__)


class Tier(enum.StrEnum):
    """Which limit applies to a request."""

    #: Pre-authentication endpoints: login, token refresh, agency signup.
    auth = "auth"
    #: Everything else, keyed by agency.
    standard = "standard"
    #: Never throttled. See the module docstring.
    exempt = "exempt"


#: Route paths that are never rate limited.
#:
#: Deliberately the literal route templates, so the startup check can verify each one still
#: matches a registered route. Keep this list short and justify every addition — an entry here
#: is an endpoint an attacker can call without limit.
EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        # Liveness. Throttling a health check takes an instance out of service under load,
        # which is the opposite of what a health check is for.
        "/health",
        # `05_API_Specification.md` Section 9, verbatim: never throttle a legally
        # time-sensitive action.
        "/v1/visits/{visit_id}/clock-in",
        "/v1/visits/{visit_id}/clock-out",
    }
)

#: Route paths limited before authentication, keyed by source address rather than agency.
AUTH_PATHS: frozenset[str] = frozenset(
    {
        "/v1/auth/login",
        "/v1/auth/refresh",
        # Public agency signup. Unlimited tenant creation is both a spam vector and a way to
        # fill the database from an unauthenticated endpoint.
        "/v1/agencies",
    }
)


def tier_for(path: str, method: str) -> Tier:
    """Which tier a route template belongs to.

    Takes the matched route *template* (`/v1/visits/{visit_id}/clock-in`), not the concrete
    request path, so limits cannot be dodged by URL shape.
    """
    if path in EXEMPT_PATHS:
        return Tier.exempt
    # POST /v1/agencies is public signup; GET/PATCH on an agency is an ordinary authenticated
    # read, so the tier depends on the method here rather than the path alone.
    if path == "/v1/agencies" and method.upper() != "POST":
        return Tier.standard
    if path in AUTH_PATHS:
        return Tier.auth
    return Tier.standard


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    #: Seconds until the next token is available. 0 when the request was allowed.
    retry_after: int
    #: Seconds until the bucket is completely full again, for `RateLimit-Reset`.
    reset_after: int


class RateLimitStore(Protocol):
    """Somewhere to keep counters.

    An interface rather than a concrete class because the in-process implementation below is
    only correct on a single instance — see its docstring.
    """

    def consume(
        self, key: str, *, limit: int, window_seconds: int, cost: float = 1.0
    ) -> Decision: ...


@dataclass
class InMemoryRateLimitStore:
    """Token buckets in this process's memory.

    **This is per-instance, not per-cluster.** Running N application instances behind a load
    balancer multiplies every limit by N, because each keeps its own buckets. That is a real
    limitation and not a hypothetical one: the documented figure is 100/minute per agency, and
    four instances would enforce 400. Redis is already in the compose stack and unused; a shared
    store is the fix, and this interface exists so that swap is a constructor argument rather
    than a rewrite.

    It is nonetheless the right thing to ship first. A limiter that works on one instance is
    strictly better than none, it needs no new infrastructure to be correct in development and
    test, and the honest cap is recorded in BUILD_STATUS rather than implied by the spec figure.
    """

    now: object = field(default=time.monotonic)
    _buckets: dict[str, _Bucket] = field(default_factory=dict)
    #: Buckets are pruned when this many keys accumulate. A *full* bucket is indistinguishable
    #: from one that has never been used, so dropping full buckets is free — which is what makes
    #: eviction safe rather than a source of allowance leaks.
    prune_at: int = 10_000

    def _clock(self) -> float:
        clock = self.now
        assert callable(clock)
        return float(clock())

    def consume(self, key: str, *, limit: int, window_seconds: int, cost: float = 1.0) -> Decision:
        now = self._clock()
        rate = limit / window_seconds  # tokens per second
        bucket = self._buckets.get(key)

        if bucket is None:
            bucket = _Bucket(tokens=float(limit), updated_at=now)
            self._buckets[key] = bucket
        else:
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(float(limit), bucket.tokens + elapsed * rate)
            bucket.updated_at = now

        if bucket.tokens >= cost:
            bucket.tokens -= cost
            allowed = True
            retry_after = 0
        else:
            allowed = False
            # Time until one more token exists. Always at least 1, because a client told to
            # retry after 0 seconds will retry immediately and be refused again.
            retry_after = max(1, math.ceil((cost - bucket.tokens) / rate))

        if len(self._buckets) > self.prune_at:
            self._prune(limit_hint=limit)

        return Decision(
            allowed=allowed,
            limit=limit,
            remaining=max(0, int(bucket.tokens)),
            retry_after=retry_after,
            reset_after=max(0, math.ceil((limit - bucket.tokens) / rate)),
        )

    def _prune(self, *, limit_hint: int) -> None:
        """Drop buckets that have refilled, since they carry no state worth keeping."""
        for key, bucket in list(self._buckets.items()):
            if bucket.tokens >= limit_hint:
                del self._buckets[key]

    def reset(self) -> None:
        self._buckets.clear()


@dataclass(frozen=True)
class RateLimitPolicy:
    """The configured limits. Separate from the store so tests can tighten them freely."""

    standard_per_minute: int
    auth_per_minute: int
    auth_per_ip_per_minute: int
    #: Clock-ins per minute from one caregiver above which something is wrong. Never blocks.
    evv_anomaly_per_minute: int


class RateLimiter:
    """Applies the policy for a request and reports the decision.

    Returns decisions rather than raising, so the caller decides how a refusal is rendered —
    which keeps this module free of HTTP concerns and testable without a server.
    """

    def __init__(self, policy: RateLimitPolicy, store: RateLimitStore | None = None) -> None:
        self.policy = policy
        self.store = store if store is not None else InMemoryRateLimitStore()

    def check(self, *, tier: Tier, agency_id: str | None, source_ip: str | None) -> Decision | None:
        """Consume allowance for one request. `None` means the tier is exempt."""
        if tier is Tier.exempt:
            return None

        ip = source_ip or "unknown"

        if tier is Tier.auth:
            # Per-address only at this layer. The tighter per-account limit needs the email,
            # which lives in the request body — and reading a body in middleware consumes the
            # receive stream out from under the handler. `check_login_attempt` applies it from
            # inside the login endpoint instead, where the email is already parsed.
            return self.store.consume(
                f"auth:ip:{ip}", limit=self.policy.auth_per_ip_per_minute, window_seconds=60
            )

        # Standard tier: per agency where we know it, otherwise per address. Falling back to the
        # address matters — without it an unauthenticated flood at any ordinary endpoint would
        # have no key at all and so no limit.
        key = f"std:agency:{agency_id}" if agency_id else f"std:ip:{ip}"
        return self.store.consume(key, limit=self.policy.standard_per_minute, window_seconds=60)

    def check_login_attempt(self, *, source_ip: str | None, email: str) -> Decision:
        """Consume allowance for one attempt against one account from one address.

        Paired with the per-address limit applied in middleware, and both are needed. Per
        address alone lets an attacker spray a single common password across thousands of
        accounts while staying under any per-account ceiling; per account alone lets them work
        through accounts one at a time from one host. Keying on the pair also means a shared
        office NAT does not lock out everyone behind it because one person mistyped.

        The email is lower-cased so that changing capitalisation does not buy a fresh bucket.
        """
        ip = source_ip or "unknown"
        return self.store.consume(
            f"auth:id:{ip}:{email.strip().lower()}",
            limit=self.policy.auth_per_minute,
            window_seconds=60,
        )

    def note_evv_volume(self, *, agency_id: str | None, caregiver_id: str | None) -> bool:
        """Count an EVV action and report whether the volume looks anomalous.

        This is the other half of `05_API_Specification.md` Section 9: clock-in and clock-out are
        exempt from throttling "but are protected by abuse-detection heuristics instead". This is
        a deliberately shallow version of that — a volume ceiling no human can reach by working —
        and it **never refuses the request**. It logs, so the signal exists and is greppable.

        What it is not: device fingerprinting, geo-velocity, or duplicate-location detection.
        Those need a device identity the app does not yet send. Recorded as a gap in
        BUILD_STATUS rather than left to look finished.
        """
        subject = caregiver_id or agency_id or "unknown"
        decision = self.store.consume(
            f"evv:volume:{subject}", limit=self.policy.evv_anomaly_per_minute, window_seconds=60
        )
        if not decision.allowed:
            logger.warning(
                "evv.anomalous_volume",
                agency_id=agency_id,
                caregiver_id=caregiver_id,
                per_minute_ceiling=self.policy.evv_anomaly_per_minute,
            )
        return not decision.allowed


def assert_rate_limit_paths_exist(app: FastAPI) -> None:
    """Fail startup if a declared exempt or auth path no longer matches a route.

    The failure this prevents is silent in both directions. A renamed clock-in endpoint would
    quietly start being throttled — breaking the one rule Section 9 states outright — and a typo
    in this module would quietly exempt nothing while looking deliberate. Same reasoning as the
    RBAC startup gate: a security decision that a rename can undo is not a decision.
    """
    from careos.core.rbac import _iter_route_specs  # local import to avoid a cycle

    registered = {spec.path for spec in _iter_route_specs(app)}
    declared = EXEMPT_PATHS | AUTH_PATHS
    missing = sorted(declared - registered)
    if missing:
        raise RuntimeError(
            "Rate-limit policy names paths that are not registered routes: "
            f"{', '.join(missing)}. Either the route was renamed — in which case its limit "
            "silently changed — or the entry is a typo that exempts nothing."
        )


def _route_index(app: FastAPI) -> list[tuple[re.Pattern[str], str, frozenset[str]]]:
    """Compiled matchers for every registered route template, built once per app.

    Cached on the app object rather than in an `lru_cache` keyed by the app, because an
    id-keyed cache would outlive a discarded app in tests and hand back matchers for routes
    that no longer exist.
    """
    cached: list[tuple[re.Pattern[str], str, frozenset[str]]] | None = getattr(
        app, "_careos_ratelimit_index", None
    )
    if cached is not None:
        return cached

    from careos.core.rbac import _iter_route_specs

    index: list[tuple[re.Pattern[str], str, frozenset[str]]] = []
    for spec in _iter_route_specs(app):
        # `/v1/visits/{visit_id}/clock-in` -> `^/v1/visits/[^/]+/clock\-in$`. Path parameters
        # never span a slash, so a single segment wildcard is the correct translation.
        pattern = (
            "^"
            + re.sub(
                r"\{[^/}]+\}", "[^/]+", re.escape(spec.path).replace("\\{", "{").replace("\\}", "}")
            )
            + "$"
        )
        index.append((re.compile(pattern), spec.path, spec.methods))

    # Fewest path parameters first, so a literal segment beats a wildcard that would also match
    # it: `/v1/visits/gaps` must resolve to itself and not to `/v1/visits/{visit_id}`. Sorting by
    # template *length* was the first attempt and is wrong — the parameterized template is the
    # longer string here, so the wildcard won. No tier differs between those two today, which is
    # exactly why it would have sat unnoticed until a literal route needed an exemption.
    index.sort(key=lambda item: (item[1].count("{"), -len(item[1])))
    app._careos_ratelimit_index = index  # type: ignore[attr-defined]
    return index


def resolve_route_path(app: FastAPI, path: str, method: str) -> tuple[str, str] | None:
    """Find the route template a request will match, before routing has happened.

    Rate limiting runs in middleware, in front of the router, so `scope["route"]` is not set
    yet. The tier must be decided from the *template* — `/v1/visits/{visit_id}/clock-in` — never
    from the concrete path, or an exemption would apply to one literal URL nobody requests.

    Matching is done against templates gathered by the same traversal the RBAC gate uses.
    Starlette's `route.matches(scope)` was tried first and silently returned no match for every
    request, because FastAPI wraps included routers in objects that do not expose routes that
    way. Everything therefore fell through to the standard tier — which meant clock-in was being
    throttled, the one thing Section 9 rules out. The test asserting clock-in survives an
    exhausted budget is what caught it; the startup path check did not, because it reads the same
    traversal that already worked.

    Returns None when nothing matches, and the caller limits those as standard: an unmatched path
    is what a scanner produces, and leaving it unlimited would be the wrong way round.
    """
    for pattern, template, methods in _route_index(app):
        if pattern.match(path) and (not methods or method.upper() in methods):
            return template, method
    return None


@lru_cache
def get_rate_limiter() -> RateLimiter:
    """The process-wide limiter, built from settings.

    Cached because the buckets *are* the state — a fresh limiter per request would allow
    everything. `reset_rate_limiter` exists so tests can start from a clean slate and tighten
    the policy without one test's traffic counting against another's.
    """
    from careos.config import get_settings

    settings = get_settings()
    return RateLimiter(
        RateLimitPolicy(
            standard_per_minute=settings.rate_limit_standard_per_minute,
            auth_per_minute=settings.rate_limit_auth_per_minute,
            auth_per_ip_per_minute=settings.rate_limit_auth_per_ip_per_minute,
            evv_anomaly_per_minute=settings.rate_limit_evv_anomaly_per_minute,
        )
    )


def reset_rate_limiter() -> None:
    get_rate_limiter.cache_clear()
