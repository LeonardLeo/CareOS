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

The buckets live in Redis, shared by every instance, so the enforced ceiling is the documented
one rather than the documented one multiplied by the instance count. `InMemoryRateLimitStore`
remains, for local development, for the test suite, and as the degraded mode when Redis is
unreachable — see `RedisRateLimitStore` for why that is a fallback rather than an outage.
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

    from careos.config import Settings

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from careos.core import metrics

logger = structlog.get_logger(__name__)


class Tier(enum.StrEnum):
    """Which limit applies to a request."""

    #: Pre-authentication endpoints: login and token refresh, tenant and platform alike.
    auth = "auth"
    #: Public self-serve sign-up. Its own tier, because it is the only unauthenticated
    #: endpoint that *creates a tenant*, and the shape of its abuse is different from a
    #: password guess: paced slowly it evades any per-minute ceiling while still filling the
    #: database, so it is limited per hour instead. See `Settings.rate_limit_signup_per_hour`.
    signup = "signup"
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
        # The CareOS operator console's own sign-in. Same reasoning as the tenant one and
        # more of it: this is the password form in front of the principal that can see every
        # tenant's operational state and take an agency offline.
        "/v1/platform/auth/login",
        "/v1/platform/auth/refresh",
    }
)

#: Public self-serve sign-up. One entry, and it is the only endpoint in the system that an
#: unauthenticated caller can use to create a row nothing garbage collects.
SIGNUP_PATHS: frozenset[str] = frozenset({"/v1/agencies"})


def tier_for(path: str, method: str) -> Tier:
    """Which tier a route template belongs to.

    Takes the matched route *template* (`/v1/visits/{visit_id}/clock-in`), not the concrete
    request path, so limits cannot be dodged by URL shape.
    """
    if path in EXEMPT_PATHS:
        return Tier.exempt
    # POST /v1/agencies is public signup; GET/PATCH on an agency is an ordinary authenticated
    # read, so the tier depends on the method here rather than the path alone.
    if path in SIGNUP_PATHS:
        return Tier.signup if method.upper() == "POST" else Tier.standard
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


def _decide(*, tokens: float, allowed: bool, limit: int, rate: float, cost: float) -> Decision:
    """Turn a post-consume token balance into the numbers a client is told.

    Shared by both stores so the two cannot drift. `tokens` is the balance *after* a successful
    consume, or the unchanged balance after a refused one — in both cases the amount actually
    available now, which is what both `Retry-After` and `RateLimit-Remaining` are about.
    """
    return Decision(
        allowed=allowed,
        limit=limit,
        remaining=max(0, int(tokens)),
        # Never zero on a refusal: a client told to retry after 0 seconds retries immediately
        # and is refused again, which is how a limiter turns into a busy-loop amplifier.
        retry_after=0 if allowed else max(1, math.ceil((cost - tokens) / rate)),
        reset_after=max(0, math.ceil((limit - tokens) / rate)),
    )


class RateLimitStore(Protocol):
    """Somewhere to keep counters.

    Async because the shared implementation talks to Redis over a socket. That cost is paid on
    every request, which is why `main.py` puts the limiter behind token *verification* (no I/O)
    but in front of session revocation (a database query): one round trip to Redis is the price
    of not paying one to Postgres for traffic that should never have been served.
    """

    async def consume(
        self, key: str, *, limit: int, window_seconds: int, cost: float = 1.0
    ) -> Decision: ...


@dataclass
class InMemoryRateLimitStore:
    """Token buckets in this process's memory.

    **Per-instance, not per-cluster.** Running N instances behind a load balancer multiplies
    every limit by N, because each keeps its own buckets. That makes this the right store for
    local development and for the test suite — no infrastructure, no clock coordination — and
    the wrong one for a deployed cluster, where `RedisRateLimitStore` is used instead and
    `validate_settings` refuses to boot production without it.

    It also stays in production as the degraded mode: when Redis is unreachable the shared store
    falls back to one of these, so an outage costs accuracy rather than availability.
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

    async def consume(
        self, key: str, *, limit: int, window_seconds: int, cost: float = 1.0
    ) -> Decision:
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

        allowed = bucket.tokens >= cost
        if allowed:
            bucket.tokens -= cost

        if len(self._buckets) > self.prune_at:
            self._prune(limit_hint=limit)

        return _decide(tokens=bucket.tokens, allowed=allowed, limit=limit, rate=rate, cost=cost)

    def _prune(self, *, limit_hint: int) -> None:
        """Drop buckets that have refilled, since they carry no state worth keeping."""
        for key, bucket in list(self._buckets.items()):
            if bucket.tokens >= limit_hint:
                del self._buckets[key]

    def reset(self) -> None:
        self._buckets.clear()


#: The token bucket, evaluated inside Redis.
#:
#: It has to be one script rather than a GET/compute/SET, because read-modify-write over a
#: network is not a limiter: N concurrent requests each read the same balance, each conclude
#: they may proceed, and the ceiling becomes N times what it says. Redis runs a script to
#: completion against a single key space, so the whole refill-and-spend is atomic.
#:
#: The clock is Redis's own `TIME`, not the caller's. Instances share the bucket, so they must
#: share the clock as well — an instance whose wall clock ran a minute fast would otherwise
#: refill everyone's bucket a minute early. Milliseconds as an integer, so the value survives
#: Lua's number formatting without losing precision the way a float epoch would.
_BUCKET_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2]) * 1000
local cost = tonumber(ARGV[3])
local rate = limit / window_ms  -- tokens per millisecond

local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)

local stored = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(stored[1])
local ts = tonumber(stored[2])

if tokens == nil or ts == nil then
  tokens = limit
else
  local elapsed = now - ts
  if elapsed < 0 then elapsed = 0 end
  tokens = math.min(limit, tokens + elapsed * rate)
end

local allowed = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
end

redis.call('HSET', key, 'tokens', tostring(tokens), 'ts', now)
-- Expire once the bucket would have refilled completely: a full bucket is indistinguishable
-- from one that never existed, so letting it disappear costs nothing and keeps idle keys from
-- accumulating for every address that ever touched the API.
redis.call('PEXPIRE', key, math.ceil((limit - tokens) / rate) + 1000)

-- As a string: a Lua number returned to Redis is truncated to an integer. Storing is unaffected
-- (numeric arguments keep their precision), but `Retry-After` is derived from this balance, and
-- deriving it from 0 rather than from 0.4 tells a caller to wait out a whole token's refill when
-- most of one is already there.
return {allowed, tostring(tokens)}
"""


class RedisRateLimitStore:
    """Token buckets in Redis, shared by every instance.

    This is what makes the documented figure true. With in-process buckets a four-instance
    deployment enforced 400 requests/minute per agency while the spec and the response headers
    both said 100.

    **What happens when Redis is down.** The request is served, and limiting falls back to an
    in-process bucket. Three options were on the table and the other two are worse:

    * *Fail closed* — refuse everything. Redis becoming a hard dependency of an API whose most
      important endpoint is a legally time-sensitive clock-in is a trade nobody would make.
    * *Fail open* — stop limiting. That removes the brute-force ceiling on login at exactly the
      moment the system is least healthy, which is when an attacker would want it removed.
    * *Fail degraded*, which is this. The limits still apply, just per instance, so the cluster
      enforces N times the ceiling instead of once — the behaviour this class replaced, and
      strictly better than either alternative.

    The fallback buckets start full at the moment of failover, so an outage hands out one extra
    allowance per key per instance. Not worth carrying a shadow copy of every bucket in memory
    to avoid.

    Failures are not swallowed. The first one logs at `error`, the outage keeps logging at
    intervals rather than once so a long degradation is visible in the middle of an incident and
    not only at its start, and recovery logs too.
    """

    #: Keys are namespaced so a Redis shared with anything else cannot collide, and so an
    #: operator can see what the limiter is holding with one `SCAN MATCH careos:rl:*`.
    prefix = "careos:rl:"

    #: How long to keep using the fallback after a failure before probing Redis again. Short,
    #: because degraded is not where we want to live; long enough that a Redis which is down
    #: rather than slow is not contacted on every single request, since each attempt costs the
    #: connect timeout and that latency lands on the caller.
    breaker_seconds = 5.0

    #: While degraded, re-log at most this often. Two lines an outage is too quiet to notice.
    warn_interval_seconds = 60.0

    def __init__(
        self,
        client: Redis,
        *,
        fallback: InMemoryRateLimitStore | None = None,
        now: object = time.monotonic,
    ) -> None:
        self._client = client
        # `register_script` gives EVALSHA with an automatic EVAL retry on NOSCRIPT, so the
        # script body crosses the wire once per Redis process rather than once per request.
        self._script = client.register_script(_BUCKET_LUA)
        self.fallback = fallback if fallback is not None else InMemoryRateLimitStore()
        self._now = now
        self._degraded = False
        self._degraded_until = 0.0
        self._warned_at = 0.0

    def _clock(self) -> float:
        clock = self._now
        assert callable(clock)
        return float(clock())

    async def consume(
        self, key: str, *, limit: int, window_seconds: int, cost: float = 1.0
    ) -> Decision:
        if self._clock() < self._degraded_until:
            return await self.fallback.consume(
                key, limit=limit, window_seconds=window_seconds, cost=cost
            )

        try:
            payload = await self._script(
                keys=[self.prefix + key], args=[limit, window_seconds, cost]
            )
        except (RedisError, OSError) as exc:
            # OSError as well as RedisError: a DNS failure or a refused connection surfaces as
            # the former through the async socket layer, and losing the fallback to an unhandled
            # exception would turn a Redis outage into a 500 on every request.
            self._degrade(exc)
            return await self.fallback.consume(
                key, limit=limit, window_seconds=window_seconds, cost=cost
            )

        self._recover()
        raw = payload[1]
        tokens = float(raw.decode() if isinstance(raw, bytes) else raw)
        return _decide(
            tokens=tokens,
            allowed=bool(int(payload[0])),
            limit=limit,
            rate=limit / window_seconds,
            cost=cost,
        )

    def _degrade(self, exc: BaseException) -> None:
        now = self._clock()
        self._degraded_until = now + self.breaker_seconds
        if not self._degraded or now - self._warned_at >= self.warn_interval_seconds:
            logger.error(
                "ratelimit.redis_unavailable",
                error=str(exc),
                error_type=type(exc).__name__,
                consequence=(
                    "rate limits are being enforced per instance until Redis returns, so the "
                    "cluster-wide ceiling is multiplied by the instance count"
                ),
            )
            self._warned_at = now
        self._degraded = True
        # The gauge is the point of the exercise: a degraded limiter still answers every
        # request, so this flag is the only outward sign that the cluster-wide ceiling is not
        # being enforced.
        metrics.rate_limit_degraded.set(1)

    def _recover(self) -> None:
        if self._degraded:
            logger.info("ratelimit.redis_recovered")
            metrics.rate_limit_degraded.set(0)
            self._degraded = False
            self._degraded_until = 0.0
            # Buckets filled during the outage are stale and would keep refusing callers who
            # have since been counted properly in Redis.
            self.fallback.reset()

    @property
    def degraded(self) -> bool:
        return self._degraded

    async def ping(self) -> bool:
        """Confirm Redis answers. Used at startup to make a misconfiguration loud, not fatal."""
        try:
            await self._client.ping()
        except (RedisError, OSError) as exc:
            self._degrade(exc)
            return False
        self._recover()
        return True

    async def reset(self, *, key_prefix: str = "") -> None:
        """Drop buckets. For tests — nothing in the request path calls this."""
        self.fallback.reset()
        pattern = f"{self.prefix}{key_prefix}*"
        async for key in self._client.scan_iter(match=pattern, count=500):
            await self._client.delete(key)

    async def aclose(self) -> None:
        await self._client.aclose()


@dataclass(frozen=True)
class RateLimitPolicy:
    """The configured limits. Separate from the store so tests can tighten them freely."""

    standard_per_minute: int
    auth_per_minute: int
    auth_per_ip_per_minute: int
    #: Clock-ins per minute from one caregiver above which something is wrong. Never blocks.
    evv_anomaly_per_minute: int
    #: Self-serve tenant creations per hour from one address.
    signup_per_hour: int


class RateLimiter:
    """Applies the policy for a request and reports the decision.

    Returns decisions rather than raising, so the caller decides how a refusal is rendered —
    which keeps this module free of HTTP concerns and testable without a server.
    """

    def __init__(self, policy: RateLimitPolicy, store: RateLimitStore | None = None) -> None:
        self.policy = policy
        self.store = store if store is not None else InMemoryRateLimitStore()

    async def check(
        self, *, tier: Tier, agency_id: str | None, source_ip: str | None
    ) -> Decision | None:
        """Consume allowance for one request. `None` means the tier is exempt."""
        if tier is Tier.exempt:
            return None

        ip = source_ip or "unknown"

        if tier is Tier.auth:
            # Per-address only at this layer. The tighter per-account limit needs the email,
            # which lives in the request body — and reading a body in middleware consumes the
            # receive stream out from under the handler. `check_login_attempt` applies it from
            # inside the login endpoint instead, where the email is already parsed.
            return await self.store.consume(
                f"auth:ip:{ip}", limit=self.policy.auth_per_ip_per_minute, window_seconds=60
            )

        if tier is Tier.signup:
            # Its own bucket and its own window. Sharing the auth bucket would have meant a
            # sign-up spending a caller's sign-in allowance and vice versa, which makes both
            # limits harder to reason about and lets a burst of sign-ups lock the same
            # network out of signing in.
            return await self.store.consume(
                f"signup:ip:{ip}", limit=self.policy.signup_per_hour, window_seconds=3600
            )

        # Standard tier: per agency where we know it, otherwise per address. Falling back to the
        # address matters — without it an unauthenticated flood at any ordinary endpoint would
        # have no key at all and so no limit.
        key = f"std:agency:{agency_id}" if agency_id else f"std:ip:{ip}"
        return await self.store.consume(
            key, limit=self.policy.standard_per_minute, window_seconds=60
        )

    async def check_login_attempt(self, *, source_ip: str | None, email: str) -> Decision:
        """Consume allowance for one attempt against one account from one address.

        Paired with the per-address limit applied in middleware, and both are needed. Per
        address alone lets an attacker spray a single common password across thousands of
        accounts while staying under any per-account ceiling; per account alone lets them work
        through accounts one at a time from one host. Keying on the pair also means a shared
        office NAT does not lock out everyone behind it because one person mistyped.

        The email is lower-cased so that changing capitalisation does not buy a fresh bucket.
        """
        ip = source_ip or "unknown"
        return await self.store.consume(
            f"auth:id:{ip}:{email.strip().lower()}",
            limit=self.policy.auth_per_minute,
            window_seconds=60,
        )

    async def note_evv_volume(self, *, agency_id: str | None, caregiver_id: str | None) -> bool:
        """Count an EVV action and report whether the volume looks anomalous.

        This is the other half of `05_API_Specification.md` Section 9: clock-in and clock-out are
        exempt from throttling "but are protected by abuse-detection heuristics instead". This is
        a deliberately shallow version of that — a volume ceiling no human can reach by working —
        and it **never refuses the request**. Returns True when anomalous so the clock handler
        can open a compliance exception; also logs and increments a counter.

        What it is not: device fingerprinting, geo-velocity, or duplicate-location detection.
        Those need a device identity the app does not yet send. Recorded as a gap in
        BUILD_STATUS rather than left to look finished.
        """
        subject = caregiver_id or agency_id or "unknown"
        decision = await self.store.consume(
            f"evv:volume:{subject}", limit=self.policy.evv_anomaly_per_minute, window_seconds=60
        )
        if not decision.allowed:
            metrics.evv_anomalous_volume_total.inc()
            logger.warning(
                "evv.anomalous_volume",
                agency_id=agency_id,
                caregiver_id=caregiver_id,
                per_minute_ceiling=self.policy.evv_anomaly_per_minute,
            )
        return not decision.allowed

    async def startup(self) -> None:
        """Report which store is live, and whether it answers.

        Deliberately not a boot gate. A Redis that is down at startup must not stop the API from
        starting: the endpoints that matter most during an incident are the exempt ones, and
        refusing to boot would take those down to protect a counter. It is logged at `error`
        instead, which is what an operator needs to see.
        """
        store = self.store
        if isinstance(store, RedisRateLimitStore):
            reachable = await store.ping()
            logger.info("ratelimit.backend", backend="redis", reachable=reachable)
        else:
            logger.info(
                "ratelimit.backend",
                backend="memory",
                note="limits apply per instance; not for multi-instance deployment",
            )

    async def aclose(self) -> None:
        store = self.store
        if isinstance(store, RedisRateLimitStore):
            await store.aclose()


def assert_rate_limit_paths_exist(app: FastAPI) -> None:
    """Fail startup if a declared exempt or auth path no longer matches a route.

    The failure this prevents is silent in both directions. A renamed clock-in endpoint would
    quietly start being throttled — breaking the one rule Section 9 states outright — and a typo
    in this module would quietly exempt nothing while looking deliberate. Same reasoning as the
    RBAC startup gate: a security decision that a rename can undo is not a decision.
    """
    from careos.core.rbac import _iter_route_specs  # local import to avoid a cycle

    registered = {spec.path for spec in _iter_route_specs(app)}
    declared = EXEMPT_PATHS | AUTH_PATHS | SIGNUP_PATHS
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


def build_rate_limit_store(settings: Settings) -> RateLimitStore:
    """Pick a store for the configured backend.

    The choice is explicit configuration rather than "use Redis if it is reachable". Inferring
    it would make the difference between a per-cluster and a per-instance ceiling depend on
    whether a socket happened to connect at boot, which is precisely the kind of silent
    downgrade this increment exists to remove. `validate_settings` refuses `memory` in
    production for the same reason.
    """
    if settings.rate_limit_backend == "memory":
        return InMemoryRateLimitStore()

    client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        # Short and deliberate: this call sits in front of every request, so a Redis that is
        # hanging must cost milliseconds before the breaker takes over, not seconds. The default
        # is no timeout at all, which would stall the whole worker on a silently dead connection.
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
        retry_on_timeout=False,
        # Detects a connection that went stale behind a load balancer's idle reaper, so the
        # first request after a quiet period does not eat the failure.
        health_check_interval=30,
    )
    return RedisRateLimitStore(client)


@lru_cache
def get_rate_limiter() -> RateLimiter:
    """The process-wide limiter, built from settings.

    Cached because the store connection and, on the memory backend, the buckets themselves are
    the state — a fresh limiter per request would allow everything.

    Deliberately without a `cache_clear` wrapper. There was one, unused; on the Redis backend it
    would have dropped a limiter still holding an open connection pool, which is a leak rather
    than a reset. Tests reach past it and clear the store or swap it, which is the thing they
    actually want and does not strand a connection.
    """
    from careos.config import get_settings

    settings = get_settings()
    return RateLimiter(
        RateLimitPolicy(
            standard_per_minute=settings.rate_limit_standard_per_minute,
            auth_per_minute=settings.rate_limit_auth_per_minute,
            auth_per_ip_per_minute=settings.rate_limit_auth_per_ip_per_minute,
            evv_anomaly_per_minute=settings.rate_limit_evv_anomaly_per_minute,
            signup_per_hour=settings.rate_limit_signup_per_hour,
        ),
        build_rate_limit_store(settings),
    )
