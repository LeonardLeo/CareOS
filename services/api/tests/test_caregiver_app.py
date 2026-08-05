"""The API surface the caregiver mobile app depends on.

`09_UX_Design_and_User_Flows.md` calls the caregiver app the highest-stakes surface in the
product, and `GET /my-visits` is the only endpoint that can tell a caregiver who they are
visiting and where. These tests pin the two properties that make it safe to hand a client's
address to a phone: it returns only visits assigned to the caller, and it returns less about
the client than the admin endpoints do.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from careos.api.v1.visits import DEFAULT_MY_VISITS_LOOKAHEAD_DAYS, MAX_MY_VISITS_WINDOW_DAYS
from careos.config import Settings, validate_settings
from careos.core.crypto import encrypt_field
from careos.db.session import tenant_session
from careos.modules.agency.models import Role
from careos.modules.audit.models import AuditLog
from careos.modules.credentialing.models import (
    Caregiver,
    EmploymentStatus,
    ExclusionCheckStatus,
)
from careos.modules.scheduling import service as scheduling
from careos.modules.scheduling.models import CarePlan, Client, ScheduledVisit
from tests.conftest import TenantFixture


async def _assigned_visit(
    tenant: TenantFixture,
    *,
    legal_name: str = "Ada Whitfield",
    address: str = "412 Ashbury Lane, Rochester NY",
    dob: str = "1948-03-11",
) -> tuple[uuid.UUID, uuid.UUID]:
    """A future visit assigned to the tenant's caregiver. Returns (visit_id, client_id).

    The address and DOB are written encrypted, the way the real intake path writes them, so
    the projection test is exercising actual decryption rather than a plaintext column.
    """
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date()
    async with tenant_session(tenant.agency_id) as session:
        care_client = Client(
            agency_id=tenant.agency_id,
            legal_name=legal_name,
            dob_encrypted=encrypt_field(dob),
            address_encrypted=encrypt_field(address),
            geo_lat=43.1566,
            geo_lng=-77.6088,
            service_state="NY",
            primary_payer_type="medicaid_waiver",
        )
        session.add(care_client)
        await session.flush()

        plan = CarePlan(
            agency_id=tenant.agency_id,
            client_id=care_client.id,
            authorized_tasks=[
                {"code": "bathing", "label": "Assist with bathing"},
                {"code": "meal_prep", "label": "Meal preparation"},
            ],
            visit_frequency_rule={"rrule": "FREQ=DAILY;COUNT=1", "start_hour": 9},
            effective_start=(datetime.now(UTC) - timedelta(days=1)).date(),
            default_service_type_code="T1019",
        )
        session.add(plan)
        await session.flush()

        visits = await scheduling.generate_visits(
            session,
            principal=tenant.principal(),
            care_plan=plan,
            window=scheduling.GenerationWindow(start=tomorrow, end=tomorrow + timedelta(days=1)),
            duration_minutes=90,
        )
        visit = visits[0]
        visit.caregiver_id = tenant.caregiver_id
        await session.flush()
        return visit.id, care_client.id


async def test_my_visits_returns_what_is_needed_to_perform_the_visit(
    client, tenant_a: TenantFixture
) -> None:
    visit_id, client_id = await _assigned_visit(tenant_a)

    response = await client.get("/v1/my-visits", headers=tenant_a.headers(Role.caregiver))
    assert response.status_code == 200, response.text
    visits = response.json()
    assert len(visits) == 1

    item = visits[0]
    assert item["id"] == str(visit_id)
    assert item["client"]["id"] == str(client_id)
    assert item["client"]["legal_name"] == "Ada Whitfield"
    # Decrypted for the caregiver who has to travel there.
    assert item["client"]["address"] == "412 Ashbury Lane, Rochester NY"
    # Coordinates are what the geofence rule compares clock-in location against.
    assert item["client"]["geo_lat"] == 43.1566
    assert item["client"]["geo_lng"] == -77.6088
    assert [t["code"] for t in item["authorized_tasks"]] == ["bathing", "meal_prep"]


async def test_my_visits_does_not_return_date_of_birth(client, tenant_a: TenantFixture) -> None:
    """Minimum necessary, enforced by the projection rather than by reviewer discipline.

    A personal-care visit does not require the client's date of birth, so it must not travel
    to a device that could be lost. Asserted against the raw response body: a nested `dob`
    added to the client schema later would fail here even if no test named it.
    """
    await _assigned_visit(tenant_a, dob="1948-03-11")

    response = await client.get("/v1/my-visits", headers=tenant_a.headers(Role.caregiver))
    assert response.status_code == 200
    assert "dob" not in response.text
    assert "1948" not in response.text


async def test_my_visits_excludes_visits_assigned_to_someone_else(
    client, tenant_a: TenantFixture
) -> None:
    """The scoping is by token, so a caregiver cannot reach a colleague's client list.

    Reassigned to a real second caregiver in the same agency rather than to an arbitrary UUID.
    The point under test is that a genuine, tenant-visible colleague's visit stays out of this
    caregiver's schedule — a nonexistent id would be filtered by the foreign key instead, and
    would prove nothing about the caregiver scoping.
    """
    visit_id, _client_id = await _assigned_visit(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        colleague = Caregiver(
            agency_id=tenant_a.agency_id,
            legal_name="Colleague Caregiver",
            employment_status=EmploymentStatus.active,
            exclusion_check_status=ExclusionCheckStatus.cleared,
            exclusion_checked_at=datetime.now(UTC),
            geo_lat=43.16,
            geo_lng=-77.61,
        )
        session.add(colleague)
        await session.flush()

        visit = await session.get(ScheduledVisit, visit_id)
        assert visit is not None
        visit.caregiver_id = colleague.id
        await session.flush()

    response = await client.get("/v1/my-visits", headers=tenant_a.headers(Role.caregiver))
    assert response.status_code == 200
    assert response.json() == []


async def test_my_visits_excludes_unassigned_visits(client, tenant_a: TenantFixture) -> None:
    """An open visit has a NULL caregiver_id; it must not fall into anyone's schedule."""
    visit_id, _client_id = await _assigned_visit(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        visit = await session.get(ScheduledVisit, visit_id)
        assert visit is not None
        visit.caregiver_id = None
        await session.flush()

    response = await client.get("/v1/my-visits", headers=tenant_a.headers(Role.caregiver))
    assert response.status_code == 200
    assert response.json() == []


async def test_my_visits_carries_evv_state_so_a_visit_can_be_resumed(
    client, tenant_a: TenantFixture
) -> None:
    """After a reload the app must be able to answer "am I clocked in?" from the server.

    This is the question the surface exists to answer. A caregiver who clocked in and then
    lost the tab has no other way to find out whether their clock-in was recorded, and
    guessing wrong means either a duplicate EVV record or an unpaid visit.
    """
    visit_id, _client_id = await _assigned_visit(tenant_a)
    headers = tenant_a.headers(Role.caregiver)

    before = await client.get("/v1/my-visits", headers=headers)
    assert before.json()[0]["clock_in_time"] is None

    now = datetime.now(UTC)
    clock_in = await client.post(
        f"/v1/visits/{visit_id}/clock-in",
        headers={**headers, "Idempotency-Key": f"ci-{uuid.uuid4()}"},
        json={
            "timestamp": now.isoformat(),
            "capture_method": "mobile_gps",
            "geo": {"lat": 43.1566, "lng": -77.6088},
            "client_local_uuid": str(uuid.uuid4()),
        },
    )
    assert clock_in.status_code == 201, clock_in.text

    after = await client.get("/v1/my-visits", headers=headers)
    item = after.json()[0]
    assert item["clock_in_time"] is not None
    assert item["clock_out_time"] is None


async def test_my_visits_is_refused_to_non_caregiver_roles(client, tenant_a: TenantFixture) -> None:
    """ "Mine" is only meaningful for a caregiver, so the endpoint does not answer others."""
    for role in (Role.owner_admin, Role.scheduler, Role.auditor):
        response = await client.get("/v1/my-visits", headers=tenant_a.headers(role))
        assert response.status_code == 403, f"{role} should not reach /my-visits"


async def test_my_visits_records_a_phi_read(client, tenant_a: TenantFixture) -> None:
    """Returning a client's name and address is a PHI disclosure and is audited as one."""
    visit_id, _client_id = await _assigned_visit(tenant_a)

    response = await client.get("/v1/my-visits", headers=tenant_a.headers(Role.caregiver))
    assert response.status_code == 200

    async with tenant_session(tenant_a.agency_id) as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "visit.caregiver_schedule_viewed")
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].after_state["visit_ids"] == [str(visit_id)]


async def test_my_visits_filters_by_date_window(client, tenant_a: TenantFixture) -> None:
    """The app fetches a window to cache; a window that excludes the visit returns nothing."""
    await _assigned_visit(tenant_a)
    headers = tenant_a.headers(Role.caregiver)
    long_ago = (datetime.now(UTC) - timedelta(days=30)).date().isoformat()
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()

    outside = await client.get(f"/v1/my-visits?from={long_ago}&to={yesterday}", headers=headers)
    assert outside.status_code == 200
    assert outside.json() == []

    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
    inside = await client.get(f"/v1/my-visits?from={tomorrow}&to={tomorrow}", headers=headers)
    assert len(inside.json()) == 1


async def test_my_visits_without_a_window_does_not_return_the_whole_employment(
    client, tenant_a: TenantFixture
) -> None:
    """An omitted window means today plus the lookahead, not every visit ever assigned.

    This response is unpaginated and carries client names and addresses. Unbounded, it grew
    with the caregiver's tenure — and the app rendered all of it under a heading that said
    "Today", so a visit from last month appeared as one happening this afternoon.
    """
    await _assigned_visit(tenant_a)  # tomorrow, inside the default window
    old_visit_id, _ = await _assigned_visit(tenant_a, legal_name="Long Ago Client")
    async with tenant_session(tenant_a.agency_id) as session:
        stale = await session.get(ScheduledVisit, old_visit_id)
        assert stale is not None
        shift = timedelta(days=DEFAULT_MY_VISITS_LOOKAHEAD_DAYS + 30)
        stale.scheduled_start -= shift
        stale.scheduled_end -= shift

    body = (await client.get("/v1/my-visits", headers=tenant_a.headers(Role.caregiver))).json()
    assert len(body) == 1, "a visit outside the default window came back anyway"
    assert body[0]["client"]["legal_name"] != "Long Ago Client"


async def test_my_visits_refuses_a_window_wider_than_the_cap(
    client, tenant_a: TenantFixture
) -> None:
    """The bound is what keeps an unpaginated PHI response a predictable size."""
    headers = tenant_a.headers(Role.caregiver)
    start = datetime.now(UTC).date()

    # A concrete window, not one derived from the constant. Asking only whether the code
    # refuses `MAX + 1` passes for any value of MAX, including one large enough to be no
    # limit at all — which is the failure this test exists to catch.
    a_year_out = (start + timedelta(days=365)).isoformat()
    response = await client.get(
        f"/v1/my-visits?from={start.isoformat()}&to={a_year_out}", headers=headers
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    # The limit itself is allowed; only wider is refused.
    at_the_limit = (start + timedelta(days=MAX_MY_VISITS_WINDOW_DAYS - 1)).isoformat()
    allowed = await client.get(
        f"/v1/my-visits?from={start.isoformat()}&to={at_the_limit}", headers=headers
    )
    assert allowed.status_code == 200, "the cap is off by one — the limit itself is refused"

    just_over = (start + timedelta(days=MAX_MY_VISITS_WINDOW_DAYS)).isoformat()
    refused = await client.get(
        f"/v1/my-visits?from={start.isoformat()}&to={just_over}", headers=headers
    )
    assert refused.status_code == 422, "one day past the cap was accepted"


async def test_my_visits_refuses_a_backwards_window(client, tenant_a: TenantFixture) -> None:
    """`to` before `from` is a caller bug, not an empty schedule.

    Returning [] would let a client with swapped parameters show a caregiver an empty day.
    """
    headers = tenant_a.headers(Role.caregiver)
    today = datetime.now(UTC).date()
    response = await client.get(
        f"/v1/my-visits?from={today.isoformat()}&to={(today - timedelta(days=1)).isoformat()}",
        headers=headers,
    )
    assert response.status_code == 422, response.text


# --- CORS -----------------------------------------------------------------------------------
#
# The caregiver app calls this API from the device, so CORS is load-bearing rather than
# cosmetic: get it wrong in one direction and no clock-in works at all, wrong in the other and
# any page a caregiver has open can read their schedule with their token. Both directions are
# pinned here.


async def test_preflight_from_an_allowed_origin_permits_the_idempotency_header(client) -> None:
    """Without Idempotency-Key named in the allowlist, every clock-in fails its preflight.

    It is not a CORS-safelisted header, so the browser withholds the real request and no
    handler ever runs — the failure is invisible server-side, which is what makes it worth a
    test rather than a comment.
    """
    response = await client.options(
        "/v1/visits/00000000-0000-0000-0000-000000000000/clock-in",
        headers={
            "Origin": "http://localhost:3001",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3001"
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "idempotency-key" in allowed
    assert "authorization" in allowed


async def test_pacing_headers_are_readable_from_the_device(client) -> None:
    """`Retry-After` is useless to this app unless CORS exposes it.

    Only a handful of response headers are readable cross-origin by default, and neither
    `Retry-After` nor the `RateLimit-*` family is among them. This app calls the API from the
    device rather than through a server of its own, so for a while the API was sending pacing
    instructions the browser silently discarded: the outbox fell back to its own backoff and
    retried a throttled server sooner than it had been asked to.

    Nothing else in the suite could catch it — every other test reaches the app through ASGI on
    a single origin, where CORS never runs.
    """
    response = await client.get("/health", headers={"Origin": "http://localhost:3001"})
    exposed = {
        h.strip().lower() for h in response.headers["access-control-expose-headers"].split(",")
    }
    assert "retry-after" in exposed
    assert {"ratelimit-limit", "ratelimit-remaining", "ratelimit-reset"} <= exposed


async def test_middleware_generated_responses_still_carry_cors_headers(
    client, tenant_a: TenantFixture
) -> None:
    """A 429 the middleware builds itself must be readable by the browser that caused it.

    Middleware order decides this, and it was wrong: `request_context` was registered before
    `CORSMiddleware` and so ran outside it, meaning every response it produced without calling
    the router — a rate-limit refusal, an auth failure, a failed commit — went out with no
    `Access-Control-Allow-Origin` at all. A browser blocks such a response entirely, so the
    caregiver app saw a network error rather than a 429, and the `Retry-After` that the expose
    list exists to publish was unreachable on the one response that carries it.

    Asserting on the refusal rather than on a 200, because the 200 path was never broken and
    would have gone on passing while this did not.
    """
    from careos.core.ratelimit import RateLimitPolicy, get_rate_limiter

    limiter = get_rate_limiter()
    original = limiter.policy
    limiter.policy = RateLimitPolicy(
        standard_per_minute=1,
        auth_per_minute=1_000_000,
        auth_per_ip_per_minute=1_000_000,
        evv_anomaly_per_minute=1_000_000,
        signup_per_hour=1_000_000,
    )
    limiter.store.reset()
    try:
        origin = {"Origin": "http://localhost:3001", **tenant_a.headers(Role.owner_admin)}
        assert (await client.get("/v1/clients", headers=origin)).status_code == 200
        refused = await client.get("/v1/clients", headers=origin)
        assert refused.status_code == 429
        assert refused.headers.get("access-control-allow-origin") == "http://localhost:3001"
        exposed = {
            h.strip().lower()
            for h in refused.headers.get("access-control-expose-headers", "").split(",")
        }
        assert "retry-after" in exposed
    finally:
        limiter.policy = original
        limiter.store.reset()

    # The same applies to an authentication failure, which the middleware also answers itself.
    rejected = await client.get(
        "/v1/clients",
        headers={"Origin": "http://localhost:3001", "Authorization": "Bearer not-a-real-token"},
    )
    assert rejected.status_code == 401
    assert rejected.headers.get("access-control-allow-origin") == "http://localhost:3001"


async def test_an_origin_outside_the_allowlist_is_not_granted_access(client) -> None:
    """A wildcard would let any site read a caregiver's schedule with their bearer token."""
    response = await client.options(
        "/v1/my-visits",
        headers={
            "Origin": "https://not-careos.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") != "https://not-careos.example.com"
    assert response.headers.get("access-control-allow-origin") != "*"


def test_production_refuses_a_localhost_cors_origin() -> None:
    """A localhost origin left in a deployed allowlist is a standing invitation.

    Any page can host a listener on 127.0.0.1, so this is a boot-time refusal rather than a
    review checklist item — the same pattern as the JWT-secret and EVV-sandbox guards.
    """
    settings = Settings(
        environment="production",
        jwt_secret="a-real-production-secret-value",
        evv_use_sandbox=False,
        cors_allowed_origins=["https://app.careos.example", "http://localhost:3001"],
    )
    with pytest.raises(RuntimeError, match="must not include localhost"):
        validate_settings(settings)


def test_production_refuses_a_wildcard_cors_origin() -> None:
    settings = Settings(
        environment="production",
        jwt_secret="a-real-production-secret-value",
        evv_use_sandbox=False,
        cors_allowed_origins=["*"],
    )
    with pytest.raises(RuntimeError, match="must not be a wildcard"):
        validate_settings(settings)
