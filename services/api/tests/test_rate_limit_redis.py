"""The shared rate-limit store, against a real Redis.

Against a *real* Redis, not a fake. The whole reason this store exists is that the arithmetic
has to be atomic across processes and the clock has to be shared; a fake would reimplement both
in Python and prove neither. The Lua script's behaviour under concurrency is the thing under
test, and only a server can exhibit it.

Skipped when no Redis is configured, so a developer without one can still run the suite — but
never skipped in CI. `test_ci_provides_a_redis_for_the_shared_store` enforces that, and it lives
in `test_rate_limits.py` rather than here: a module-level `skipif` applies to every test in the
file regardless of definition order, so a guard placed in this module would be skipped by the
very condition it exists to catch. It was, until the skip summary was actually read.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from careos.core.ratelimit import (
    InMemoryRateLimitStore,
    RateLimiter,
    RateLimitPolicy,
    RedisRateLimitStore,
    Tier,
    get_rate_limiter,
)
from careos.modules.agency.models import Role
from tests.conftest import TenantFixture

REDIS_URL = os.environ.get("CAREOS_TEST_REDIS_URL", "")

pytestmark = pytest.mark.skipif(
    not REDIS_URL, reason="set CAREOS_TEST_REDIS_URL to run the shared rate-limit store tests"
)


@pytest.fixture
async def redis_store():
    """A store with a key namespace of its own, torn down afterwards.

    Per-test namespacing rather than FLUSHDB: the connection may be pointed at a Redis somebody
    else is using, and a test suite that wipes a database it did not create is a bad neighbour.
    """
    client = Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
    try:
        await client.ping()
    except (RedisConnectionError, OSError) as exc:  # pragma: no cover - configuration error
        pytest.fail(f"CAREOS_TEST_REDIS_URL is set but unreachable: {exc}")

    store = RedisRateLimitStore(client)
    store.prefix = f"careos:rl:test:{uuid.uuid4().hex}:"
    yield store
    await store.reset()
    await store.aclose()


async def test_a_bucket_allows_its_limit_then_refuses(redis_store: RedisRateLimitStore) -> None:
    for _ in range(5):
        assert (await redis_store.consume("k", limit=5, window_seconds=60)).allowed

    refused = await redis_store.consume("k", limit=5, window_seconds=60)
    assert not refused.allowed
    assert refused.remaining == 0
    assert refused.retry_after >= 1


async def test_keys_do_not_share_allowance(redis_store: RedisRateLimitStore) -> None:
    assert (await redis_store.consume("a", limit=1, window_seconds=60)).allowed
    assert not (await redis_store.consume("a", limit=1, window_seconds=60)).allowed
    assert (await redis_store.consume("b", limit=1, window_seconds=60)).allowed


async def test_a_fractional_balance_survives_the_lua_boundary(
    redis_store: RedisRateLimitStore,
) -> None:
    """Why the balance is returned as a string.

    A Lua number returned to Redis is truncated to an integer, so a bucket holding 0.4 tokens
    would report 0. The stored value is unaffected — Redis formats numeric *arguments* with full
    precision — so this does not leak allowance. What it corrupts is `Retry-After`: computed
    from 0 rather than 0.4, the client is told to wait for a whole token's worth of refill when
    most of one is already there, which on a slow-refilling bucket is minutes of overstatement.

    The bucket is seeded directly rather than by waiting for it, so the assertion is on an exact
    number instead of on however much a sleep happened to refill.
    """
    key = f"{redis_store.prefix}frac"
    now_ms = int((await redis_store._client.time())[0]) * 1000
    await redis_store._client.hset(key, mapping={"tokens": "0.4", "ts": now_ms})

    # 6/minute refills at 0.1 tokens/second: 0.6 tokens short is 6 seconds, an empty bucket 10.
    refused = await redis_store.consume("frac", limit=6, window_seconds=60)
    assert not refused.allowed
    assert refused.retry_after == 6, "the balance was rounded down before Retry-After was derived"


async def test_a_bucket_refills(redis_store: RedisRateLimitStore) -> None:
    """Uses a wide window so a real second of wall clock is a visible fraction of it."""
    for _ in range(4):
        assert (await redis_store.consume("refill", limit=4, window_seconds=1)).allowed
    assert not (await redis_store.consume("refill", limit=4, window_seconds=1)).allowed

    await asyncio.sleep(0.4)
    assert (await redis_store.consume("refill", limit=4, window_seconds=1)).allowed


async def test_the_key_expires_once_the_bucket_would_be_full(
    redis_store: RedisRateLimitStore,
) -> None:
    """Otherwise every address that ever touched the API keeps a key forever.

    A full bucket is indistinguishable from an absent one, so expiry at the refill point loses
    no state — and the TTL must never be shorter than that, or a caller would get a fresh
    allowance by waiting less than their bucket needed.
    """
    await redis_store.consume("ttl", limit=60, window_seconds=60)
    ttl_ms = await redis_store._client.pttl(f"{redis_store.prefix}ttl")
    # One token spent out of 60/minute is a one-second refill, plus the one-second margin.
    assert 1_000 < ttl_ms <= 3_000


async def test_two_instances_share_one_budget(redis_store: RedisRateLimitStore) -> None:
    """The claim this whole module exists to make.

    Two limiters, two stores, two connections — one ceiling. With in-process buckets each would
    have allowed the full three, and the cluster would have enforced six while the response
    headers said three.
    """
    policy = RateLimitPolicy(
        standard_per_minute=3,
        auth_per_minute=99,
        auth_per_ip_per_minute=99,
        evv_anomaly_per_minute=99,
        signup_per_hour=99,
    )
    second_client = Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
    second_store = RedisRateLimitStore(second_client)
    second_store.prefix = redis_store.prefix  # same namespace: one cluster, not two

    instance_a = RateLimiter(policy, redis_store)
    instance_b = RateLimiter(policy, second_store)

    try:
        allowed = 0
        # Alternate between instances, as a load balancer would.
        for instance in (instance_a, instance_b, instance_a, instance_b, instance_a, instance_b):
            decision = await instance.check(
                tier=Tier.standard, agency_id="shared-agency", source_ip="1.2.3.4"
            )
            assert decision is not None
            allowed += int(decision.allowed)
        assert allowed == 3
    finally:
        await second_client.aclose()


async def test_concurrent_requests_cannot_all_win(redis_store: RedisRateLimitStore) -> None:
    """Why the bucket is a Lua script rather than a GET, some arithmetic, and a SET.

    Read-modify-write over a network is not a limiter: N callers in flight at once each read the
    same balance, each conclude there is room, and the ceiling becomes N times what it says.
    Fifty concurrent attempts against a budget of five must yield exactly five.
    """
    results = await asyncio.gather(
        *(redis_store.consume("race", limit=5, window_seconds=60) for _ in range(50))
    )
    assert sum(1 for decision in results if decision.allowed) == 5


async def test_the_clock_comes_from_redis_not_the_caller(
    redis_store: RedisRateLimitStore,
) -> None:
    """Instances share a bucket, so they must share a clock.

    The store is handed a monotonic clock that never advances. If refill were computed from it,
    the bucket would never recover; it recovers because the script reads Redis's own `TIME`.
    An instance whose wall clock ran fast would otherwise refill everyone's bucket early.
    """
    frozen = RedisRateLimitStore(redis_store._client, now=lambda: 0.0)
    frozen.prefix = redis_store.prefix

    for _ in range(4):
        assert (await frozen.consume("clock", limit=4, window_seconds=1)).allowed
    assert not (await frozen.consume("clock", limit=4, window_seconds=1)).allowed
    await asyncio.sleep(0.4)
    assert (await frozen.consume("clock", limit=4, window_seconds=1)).allowed


# --- Degradation ----------------------------------------------------------------------------


@pytest.fixture
def unreachable_store():
    """A store pointed at a port nothing is listening on."""
    client = Redis.from_url(
        "redis://127.0.0.1:1/0", decode_responses=True, socket_connect_timeout=0.05
    )
    return RedisRateLimitStore(client, fallback=InMemoryRateLimitStore())


async def test_a_redis_outage_degrades_to_local_limiting_rather_than_no_limiting(
    unreachable_store: RedisRateLimitStore,
) -> None:
    """Fail degraded, not fail open.

    Availability first — clock-in must not depend on Redis — but the login ceiling is exactly
    what an attacker would want removed during an outage, so the in-process bucket keeps
    applying it. The limit still holds; it holds per instance.
    """
    assert (await unreachable_store.consume("down", limit=2, window_seconds=60)).allowed
    assert (await unreachable_store.consume("down", limit=2, window_seconds=60)).allowed
    refused = await unreachable_store.consume("down", limit=2, window_seconds=60)
    assert not refused.allowed
    assert refused.retry_after >= 1
    assert unreachable_store.degraded is True


async def test_an_outage_stops_costing_a_connect_attempt_per_request(
    unreachable_store: RedisRateLimitStore,
) -> None:
    """The breaker exists for latency, not for tidiness.

    Every attempt against a dead Redis costs the connect timeout, and that latency lands on the
    caller. After the first failure the store must serve from the fallback without touching the
    socket until the breaker window elapses.
    """
    attempts = 0
    original = unreachable_store._script

    async def counting(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        return await original(*args, **kwargs)

    unreachable_store._script = counting  # type: ignore[assignment]

    for _ in range(10):
        await unreachable_store.consume("breaker", limit=100, window_seconds=60)

    assert attempts == 1, "the breaker should have short-circuited the remaining nine"


async def test_recovery_is_noticed_and_stale_local_buckets_are_dropped(
    redis_store: RedisRateLimitStore,
) -> None:
    """A bucket spent during an outage must not keep refusing a caller once Redis is back.

    The fallback and Redis count separately, so after failover the local copy holds a balance
    nobody has been charged for centrally. Carrying it forward would refuse requests the shared
    budget has room for.
    """
    store = RedisRateLimitStore(redis_store._client, fallback=InMemoryRateLimitStore())
    store.prefix = redis_store.prefix

    # Force the degraded path once, spending the local bucket dry.
    store._degrade(RuntimeError("simulated outage"))
    store._degraded_until = 0.0  # the window has elapsed; the next call probes Redis
    assert store.degraded is True

    await store.fallback.consume("recovered", limit=1, window_seconds=60)
    assert not (await store.fallback.consume("recovered", limit=1, window_seconds=60)).allowed

    # Redis is healthy, so this call succeeds and clears the degraded state.
    assert (await store.consume("recovered", limit=1, window_seconds=60)).allowed
    assert store.degraded is False
    # And the stale local bucket is gone rather than still refusing.
    assert (await store.fallback.consume("recovered", limit=1, window_seconds=60)).allowed


async def test_ping_reports_reachability_without_raising(
    redis_store: RedisRateLimitStore, unreachable_store: RedisRateLimitStore
) -> None:
    """Startup calls this. It must never be the reason the API fails to boot."""
    assert await redis_store.ping() is True
    assert await unreachable_store.ping() is False


# --- Through the middleware -------------------------------------------------------------------


@pytest.fixture
async def live_redis_limiter(redis_store: RedisRateLimitStore):
    """Point the running app's limiter at Redis for the duration of one test."""
    limiter = get_rate_limiter()
    original_store, original_policy = limiter.store, limiter.policy
    limiter.store = redis_store
    yield limiter
    limiter.store, limiter.policy = original_store, original_policy


async def test_the_middleware_enforces_the_shared_limit(
    client, tenant_a: TenantFixture, live_redis_limiter: RateLimiter
) -> None:
    """The store is only useful if the request path actually awaits it.

    Every store test above calls `consume` directly. This one goes through the middleware, the
    tier resolution, and the error handler — the places where making the limiter async could
    have left a coroutine unawaited, which Python answers with a truthy object rather than a
    decision and so with a limiter that silently allows everything.
    """
    live_redis_limiter.policy = RateLimitPolicy(
        standard_per_minute=2,
        auth_per_minute=1_000_000,
        auth_per_ip_per_minute=1_000_000,
        evv_anomaly_per_minute=1_000_000,
        signup_per_hour=1_000_000,
    )
    headers = tenant_a.headers(Role.owner_admin)

    assert (await client.get("/v1/clients", headers=headers)).status_code == 200
    assert (await client.get("/v1/clients", headers=headers)).status_code == 200

    refused = await client.get("/v1/clients", headers=headers)
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(refused.headers["Retry-After"]) >= 1


async def test_clock_in_is_never_throttled_on_the_shared_store(
    client, tenant_a: TenantFixture, live_redis_limiter: RateLimiter
) -> None:
    """Section 9's one hard rule, re-checked against the store production will use.

    Worth repeating here rather than trusting the memory-backed version: the exemption and the
    EVV volume counter both changed shape when the limiter became async, and the volume counter
    now issues a Redis call on the clock-in path — a call that must never be able to refuse it.
    """
    from tests.conftest import make_client_with_plan

    headers = tenant_a.headers(Role.owner_admin)
    _client_id, plan_id = await make_client_with_plan(tenant_a)
    generated = await client.post(
        f"/v1/care-plans/{plan_id}/generate-visits",
        headers=headers,
        json={
            "window_start": "2026-08-03",
            "window_end": "2026-08-05",
            "duration_minutes": 60,
        },
    )
    assert generated.status_code == 201, generated.text
    visit_id = generated.json()[0]["id"]

    # Spend the entire standard budget, and set the anomaly ceiling below one clock-in so the
    # volume counter is refusing too. Neither may reach the clock-in.
    live_redis_limiter.policy = RateLimitPolicy(
        standard_per_minute=1,
        auth_per_minute=1_000_000,
        auth_per_ip_per_minute=1_000_000,
        evv_anomaly_per_minute=1,
        signup_per_hour=1_000_000,
    )
    assert (await client.get("/v1/clients", headers=headers)).status_code == 200
    assert (await client.get("/v1/clients", headers=headers)).status_code == 429

    clock_in = await client.post(
        f"/v1/visits/{visit_id}/clock-in",
        headers={**headers, "Idempotency-Key": f"ci-{uuid.uuid4()}"},
        json={
            "timestamp": "2026-08-03T09:00:00Z",
            "capture_method": "mobile_gps",
            "client_local_uuid": str(uuid.uuid4()),
        },
    )
    assert clock_in.status_code != 429, clock_in.text
