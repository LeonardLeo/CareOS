"""Rate limiting (`05_API_Specification.md` Section 9).

Two properties matter more than the rest, and they pull in opposite directions:

* **Clock-in and clock-out are never throttled.** Section 9 says so outright, and the reason is
  that an EVV record which could not be created because someone else's traffic filled the
  agency's budget becomes this caregiver's unpaid visit and the agency's compliance exception.
  A limiter that gets this wrong is worse than no limiter.
* **Login is limited.** The spec keys everything by agency, which cannot apply before a tenant
  is known — so under a literal reading the password form is the one place with no ceiling.

The suite as a whole runs with limits raised out of the way (see conftest). These tests tighten
the live policy instead, so what they assert is the real middleware path rather than a
reimplementation of it.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI

from careos.core.ratelimit import (
    AUTH_PATHS,
    EXEMPT_PATHS,
    InMemoryRateLimitStore,
    RateLimiter,
    RateLimitPolicy,
    Tier,
    assert_rate_limit_paths_exist,
    get_rate_limiter,
    tier_for,
)
from careos.modules.agency.models import Role
from tests.conftest import TenantFixture


@pytest.fixture
def tight_limits():
    """Tighten the running limiter, then restore it.

    Mutating the live instance rather than injecting a new one is deliberate: middleware and the
    login handler both reach it through `get_rate_limiter()`, so a substitute would have to be
    threaded through both and could drift from what production uses.
    """
    limiter = get_rate_limiter()
    original = limiter.policy

    def apply(**overrides: int):
        limiter.policy = RateLimitPolicy(
            standard_per_minute=overrides.get("standard", 1_000_000),
            auth_per_minute=overrides.get("auth", 1_000_000),
            auth_per_ip_per_minute=overrides.get("auth_ip", 1_000_000),
            evv_anomaly_per_minute=overrides.get("evv", 1_000_000),
        )
        store = limiter.store
        if hasattr(store, "reset"):
            store.reset()
        return limiter

    yield apply
    limiter.policy = original
    if hasattr(limiter.store, "reset"):
        limiter.store.reset()


# --- Tier assignment ------------------------------------------------------------------------


def test_clock_in_and_clock_out_are_exempt() -> None:
    """The one rule Section 9 states outright."""
    assert tier_for("/v1/visits/{visit_id}/clock-in", "POST") is Tier.exempt
    assert tier_for("/v1/visits/{visit_id}/clock-out", "POST") is Tier.exempt


def test_login_and_refresh_are_in_the_auth_tier() -> None:
    assert tier_for("/v1/auth/login", "POST") is Tier.auth
    assert tier_for("/v1/auth/refresh", "POST") is Tier.auth


def test_agency_signup_is_auth_tier_but_reading_an_agency_is_not() -> None:
    """Same path, different exposure: POST is public signup, GET needs a token.

    Treating the path alone as pre-authentication would apply an address-keyed limit to ordinary
    authenticated reads, which is both wrong and easy to do by accident.
    """
    assert tier_for("/v1/agencies", "POST") is Tier.auth
    assert tier_for("/v1/agencies", "GET") is Tier.standard


def test_everything_else_is_standard() -> None:
    assert tier_for("/v1/clients", "GET") is Tier.standard
    assert tier_for("/v1/my-visits", "GET") is Tier.standard
    assert tier_for("/v1/visits/{visit_id}/assign", "POST") is Tier.standard


def test_the_exempt_list_stays_short() -> None:
    """A guard against exemptions accumulating.

    Every entry is an endpoint an attacker may call without limit, so growth here should require
    someone to change this number and think about why.
    """
    assert {
        "/health",
        "/v1/visits/{visit_id}/clock-in",
        "/v1/visits/{visit_id}/clock-out",
    } == EXEMPT_PATHS


def test_startup_check_rejects_a_path_that_no_longer_exists(app: FastAPI) -> None:
    """Renaming clock-in must not silently start throttling it."""
    assert_rate_limit_paths_exist(app)  # the real app passes

    rogue = FastAPI()  # no routes at all
    with pytest.raises(RuntimeError, match="not registered routes"):
        assert_rate_limit_paths_exist(rogue)


def test_declared_paths_are_all_registered(app: FastAPI) -> None:
    """The same assertion the app makes at boot, stated here so a failure names itself."""
    from careos.core.rbac import _iter_route_specs

    registered = {spec.path for spec in _iter_route_specs(app)}
    assert registered >= (EXEMPT_PATHS | AUTH_PATHS)


# --- The token bucket -----------------------------------------------------------------------


def test_a_bucket_allows_its_limit_then_refuses() -> None:
    clock = [1000.0]
    store = InMemoryRateLimitStore(now=lambda: clock[0])

    for _ in range(5):
        assert store.consume("k", limit=5, window_seconds=60).allowed

    refused = store.consume("k", limit=5, window_seconds=60)
    assert not refused.allowed
    assert refused.remaining == 0
    # Never zero: a client told to retry after 0 seconds retries at once and is refused again.
    assert refused.retry_after >= 1


def test_a_bucket_refills_over_time() -> None:
    clock = [1000.0]
    store = InMemoryRateLimitStore(now=lambda: clock[0])
    for _ in range(60):
        store.consume("k", limit=60, window_seconds=60)
    assert not store.consume("k", limit=60, window_seconds=60).allowed

    clock[0] += 2.0  # 60/minute is one per second
    assert store.consume("k", limit=60, window_seconds=60).allowed


def test_a_bucket_does_not_allow_a_double_burst_at_a_boundary() -> None:
    """The reason for a bucket rather than a fixed window.

    A fixed window lets a caller spend the whole allowance at the end of one window and again at
    the start of the next. Sixty requests then sixty more one second later is 120 in about a
    second, which is what this rules out.
    """
    clock = [1000.0]
    store = InMemoryRateLimitStore(now=lambda: clock[0])
    for _ in range(60):
        assert store.consume("k", limit=60, window_seconds=60).allowed

    clock[0] += 1.0
    allowed_after_a_second = sum(
        1 for _ in range(60) if store.consume("k", limit=60, window_seconds=60).allowed
    )
    assert allowed_after_a_second == 1


def test_keys_do_not_share_allowance() -> None:
    store = InMemoryRateLimitStore()
    assert store.consume("a", limit=1, window_seconds=60).allowed
    assert not store.consume("a", limit=1, window_seconds=60).allowed
    assert store.consume("b", limit=1, window_seconds=60).allowed


def test_pruning_keeps_partly_spent_buckets() -> None:
    """Eviction must not hand allowance back to an active caller."""
    store = InMemoryRateLimitStore(prune_at=1)
    store.consume("spent", limit=2, window_seconds=60)  # 1 of 2 left
    store.consume("full-x", limit=2, window_seconds=60)
    store.consume("full-x", limit=2, window_seconds=60)  # spends it too

    # Force a prune with a fresh key.
    store.consume("trigger", limit=2, window_seconds=60)
    # The partly-spent bucket must still refuse once its allowance runs out.
    assert store.consume("spent", limit=2, window_seconds=60).allowed
    assert not store.consume("spent", limit=2, window_seconds=60).allowed


def test_a_limiter_returns_no_decision_for_an_exempt_tier() -> None:
    limiter = RateLimiter(
        RateLimitPolicy(
            standard_per_minute=1,
            auth_per_minute=1,
            auth_per_ip_per_minute=1,
            evv_anomaly_per_minute=1,
        )
    )
    assert limiter.check(tier=Tier.exempt, agency_id="a", source_ip="1.2.3.4") is None


def test_standard_tier_is_keyed_by_agency_not_address() -> None:
    """Two agencies behind one address must not consume each other's allowance."""
    limiter = RateLimiter(
        RateLimitPolicy(
            standard_per_minute=1,
            auth_per_minute=99,
            auth_per_ip_per_minute=99,
            evv_anomaly_per_minute=99,
        )
    )
    first = limiter.check(tier=Tier.standard, agency_id="agency-a", source_ip="1.2.3.4")
    assert first is not None and first.allowed
    again = limiter.check(tier=Tier.standard, agency_id="agency-a", source_ip="1.2.3.4")
    assert again is not None and not again.allowed

    other = limiter.check(tier=Tier.standard, agency_id="agency-b", source_ip="1.2.3.4")
    assert other is not None and other.allowed


def test_unauthenticated_standard_traffic_is_keyed_by_address() -> None:
    """Otherwise a flood with no token would have no key, and so no limit at all."""
    limiter = RateLimiter(
        RateLimitPolicy(
            standard_per_minute=1,
            auth_per_minute=99,
            auth_per_ip_per_minute=99,
            evv_anomaly_per_minute=99,
        )
    )
    assert limiter.check(tier=Tier.standard, agency_id=None, source_ip="9.9.9.9").allowed  # type: ignore[union-attr]
    assert not limiter.check(tier=Tier.standard, agency_id=None, source_ip="9.9.9.9").allowed  # type: ignore[union-attr]


def test_login_attempts_are_counted_per_account_and_address() -> None:
    limiter = RateLimiter(
        RateLimitPolicy(
            standard_per_minute=99,
            auth_per_minute=2,
            auth_per_ip_per_minute=99,
            evv_anomaly_per_minute=99,
        )
    )
    for _ in range(2):
        assert limiter.check_login_attempt(source_ip="1.1.1.1", email="a@example.com").allowed
    assert not limiter.check_login_attempt(source_ip="1.1.1.1", email="a@example.com").allowed

    # A different account from the same address still has its own allowance; spraying is caught
    # by the per-address counter instead.
    assert limiter.check_login_attempt(source_ip="1.1.1.1", email="b@example.com").allowed
    # And the same account from elsewhere, since the key is the pair.
    assert limiter.check_login_attempt(source_ip="2.2.2.2", email="a@example.com").allowed


def test_login_email_case_does_not_buy_a_fresh_bucket() -> None:
    limiter = RateLimiter(
        RateLimitPolicy(
            standard_per_minute=99,
            auth_per_minute=1,
            auth_per_ip_per_minute=99,
            evv_anomaly_per_minute=99,
        )
    )
    assert limiter.check_login_attempt(source_ip="1.1.1.1", email="Ada@Example.com").allowed
    assert not limiter.check_login_attempt(source_ip="1.1.1.1", email="ada@example.com").allowed


def test_evv_volume_is_flagged_but_never_refused() -> None:
    """Section 9's "abuse-detection heuristics instead" — detection, not throttling."""
    limiter = RateLimiter(
        RateLimitPolicy(
            standard_per_minute=99,
            auth_per_minute=99,
            auth_per_ip_per_minute=99,
            evv_anomaly_per_minute=2,
        )
    )
    assert limiter.note_evv_volume(agency_id="a", caregiver_id="cg") is False
    assert limiter.note_evv_volume(agency_id="a", caregiver_id="cg") is False
    # Third in the window is anomalous — reported to the caller, and the caller does not block.
    assert limiter.note_evv_volume(agency_id="a", caregiver_id="cg") is True


# --- Over HTTP ------------------------------------------------------------------------------


async def test_a_standard_endpoint_returns_429_with_retry_after(
    client, tenant_a: TenantFixture, tight_limits
) -> None:
    tight_limits(standard=2)
    headers = tenant_a.headers(Role.owner_admin)

    assert (await client.get("/v1/clients", headers=headers)).status_code == 200
    assert (await client.get("/v1/clients", headers=headers)).status_code == 200

    refused = await client.get("/v1/clients", headers=headers)
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    # The header matters more than the body: a client that has to parse JSON to learn when to
    # come back will mostly retry immediately instead.
    assert int(refused.headers["Retry-After"]) >= 1


async def test_rate_limit_headers_are_present_before_the_limit_is_reached(
    client, tenant_a: TenantFixture, tight_limits
) -> None:
    """A client should be able to slow down before it is turned away, not after."""
    tight_limits(standard=5)
    response = await client.get("/v1/clients", headers=tenant_a.headers(Role.owner_admin))
    assert response.status_code == 200
    assert response.headers["RateLimit-Limit"] == "5"
    assert int(response.headers["RateLimit-Remaining"]) < 5


async def test_clock_in_is_never_throttled(client, tenant_a: TenantFixture, tight_limits) -> None:
    """The property this whole module exists to protect.

    The standard budget is set to zero-in-practice and a clock-in still goes through. Asserting
    "not 429" rather than "201" keeps the test about throttling: a clock-in can legitimately fail
    a compliance gate, and that is a different answer with a different status.
    """
    from tests.conftest import make_client_with_plan

    tight_limits(standard=1)
    headers = tenant_a.headers(Role.owner_admin)

    # Set the visit up before tightening bites — this is the part that needs standard requests.
    _client_id, plan_id = await make_client_with_plan(tenant_a)
    tight_limits(standard=1_000_000)
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

    # Now spend the entire standard allowance.
    tight_limits(standard=1)
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


async def test_health_is_never_throttled(client, tight_limits) -> None:
    """A throttled health check removes a healthy instance from rotation under load."""
    tight_limits(standard=1)
    for _ in range(5):
        assert (await client.get("/health")).status_code == 200


async def test_repeated_bad_passwords_for_one_account_are_refused(
    client, tenant_a: TenantFixture, tight_limits
) -> None:
    """Brute force against one account. The gap that made this increment worth doing."""
    tight_limits(auth=3, auth_ip=1_000_000)
    email = f"target-{uuid.uuid4().hex[:8]}@example.com"

    seen = []
    for _ in range(5):
        response = await client.post(
            "/v1/auth/login", json={"email": email, "password": "wrong-password-guess"}
        )
        seen.append(response.status_code)

    # The first few are ordinary auth failures; then the limiter takes over.
    assert 401 in seen
    assert seen[-1] == 429
    assert seen.count(429) == 2


async def test_a_correct_password_does_not_escape_the_limit(
    client, tenant_a: TenantFixture, tight_limits
) -> None:
    """Allowance is spent before the password is checked.

    Charging only failures would let an attacker who has one working credential probe without
    limit, and the counter is also what makes a successful guess visible.
    """
    password = "a-sufficiently-long-password"
    email = f"real-{uuid.uuid4().hex[:8]}@example.com"
    invited = await client.post(
        f"/v1/agencies/{tenant_a.agency_id}/users",
        headers=tenant_a.headers(Role.owner_admin),
        json={"email": email, "role": "scheduler", "initial_password": password},
    )
    assert invited.status_code == 201

    tight_limits(auth=2, auth_ip=1_000_000)
    assert (
        await client.post("/v1/auth/login", json={"email": email, "password": password})
    ).status_code == 200
    assert (
        await client.post("/v1/auth/login", json={"email": email, "password": password})
    ).status_code == 200
    exhausted = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert exhausted.status_code == 429
    assert int(exhausted.headers["Retry-After"]) >= 1


async def test_credential_spraying_across_accounts_is_refused(client, tight_limits) -> None:
    """Per-account limits alone would miss this: one guess against thousands of addresses."""
    tight_limits(auth=1_000_000, auth_ip=3)

    statuses = [
        (
            await client.post(
                "/v1/auth/login",
                json={"email": f"spray-{i}@example.com", "password": "one-common-password"},
            )
        ).status_code
        for i in range(5)
    ]
    assert statuses[-1] == 429


async def test_agency_signup_is_limited(client, tight_limits) -> None:
    """Unlimited tenant creation from an unauthenticated endpoint is a database-filling vector."""
    tight_limits(auth_ip=2)

    def body(n: int) -> dict:
        suffix = uuid.uuid4().hex[:8]
        return {
            "legal_name": f"Spam Agency {n} {suffix}",
            "service_states": ["NY"],
            "service_lines": ["home_care"],
            "accepted_payer_types": ["medicaid_waiver"],
            "owner_email": f"spam-{suffix}@example.com",
            "owner_password": "a-sufficiently-long-password",
            "owner_full_name": "Spam Owner",
        }

    statuses = [(await client.post("/v1/agencies", json=body(n))).status_code for n in range(4)]
    assert 429 in statuses


def test_a_literal_path_resolves_to_itself_not_to_a_wildcard_sibling(app: FastAPI) -> None:
    """`/v1/visits/gaps` and `/v1/visits/{visit_id}` both match that URL.

    Whichever wins decides the tier, so the more specific template has to. The first version
    ordered templates by length, which picked the *parameterized* one because it is the longer
    string. Both are standard-tier today, so nothing broke — the bug would have surfaced the
    first time a literal route needed an exemption its wildcard sibling did not have.
    """
    from careos.core.ratelimit import resolve_route_path

    resolved = resolve_route_path(app, "/v1/visits/gaps", "GET")
    assert resolved is not None
    assert resolved[0] == "/v1/visits/gaps"


def test_a_clock_in_url_resolves_to_the_exempt_template(app: FastAPI) -> None:
    """The exemption has to apply to every visit id, not to a literal path nobody requests."""
    from careos.core.ratelimit import resolve_route_path

    resolved = resolve_route_path(app, f"/v1/visits/{uuid.uuid4()}/clock-in", "POST")
    assert resolved is not None
    assert resolved[0] == "/v1/visits/{visit_id}/clock-in"
    assert tier_for(resolved[0], "POST") is Tier.exempt
