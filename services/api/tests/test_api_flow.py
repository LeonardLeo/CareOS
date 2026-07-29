"""End-to-end API tests over the Phase 1 golden path.

Walks `03_Technical_Architecture.md` Section 6 through HTTP: provision a tenant, add a
client and care plan, generate visits, hire and clear a caregiver, assign, then clock in and
out — asserting the API-level contracts from `05_API_Specification.md` along the way.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from careos.modules.agency.models import Role
from tests.conftest import TenantFixture


async def test_full_phase1_golden_path(client, reference_data: None) -> None:
    # 1. Provision the tenant (US-1.1.1).
    unique = uuid.uuid4().hex[:8]
    create = await client.post(
        "/v1/agencies",
        json={
            "legal_name": "Golden Path Home Care",
            "tax_id": "12-3456789",
            "service_states": ["ny"],
            "service_lines": ["home_care"],
            "accepted_payer_types": ["medicaid_waiver"],
            "owner_email": f"owner-{unique}@goldenpath.example.com",
            "owner_password": "a-sufficiently-long-password",
        },
    )
    assert create.status_code == 201, create.text
    agency = create.json()
    assert agency["service_states"] == ["NY"], "state codes should be normalized to upper case"

    # 2. Log in.
    login = await client.post(
        "/v1/auth/login",
        json={
            "email": f"owner-{unique}@goldenpath.example.com",
            "password": "a-sufficiently-long-password",
        },
    )
    assert login.status_code == 200
    tokens = login.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert tokens["expires_in"] == 900

    # 3. Create a client and care plan.
    client_response = await client.post(
        "/v1/clients",
        headers=headers,
        json={
            "legal_name": "Eleanor Client",
            "dob": "1940-03-02",
            "address": "1 Test Street, New York NY",
            "geo_lat": 40.7128,
            "geo_lng": -74.0060,
            "service_state": "NY",
            "primary_payer_type": "medicaid_waiver",
        },
    )
    assert client_response.status_code == 201, client_response.text
    client_id = client_response.json()["id"]

    plan_response = await client.post(
        f"/v1/clients/{client_id}/care-plans",
        headers=headers,
        json={
            "authorized_tasks": [{"code": "bathing", "label": "Assist with bathing"}],
            "visit_frequency_rule": {"rrule": "FREQ=DAILY;COUNT=2", "start_hour": 9},
            "effective_start": datetime.now(UTC).date().isoformat(),
            "default_service_type_code": "T1019",
        },
    )
    assert plan_response.status_code == 201, plan_response.text
    plan_id = plan_response.json()["id"]

    # 3a. The plan is retrievable by client, and carries its recurrence rule.
    #
    # Both matter to the same screen. Without the list, a plan's id existed only in the
    # redirect that created it, so returning to a client later left no way to generate
    # further visits from a plan that already existed. Without the rule in the response, a
    # scheduler about to materialize a month of work cannot see the pattern that work will
    # follow, and with more than one plan cannot tell which is selected.
    plan_list = await client.get(f"/v1/clients/{client_id}/care-plans", headers=headers)
    assert plan_list.status_code == 200, plan_list.text
    listed = plan_list.json()
    assert [p["id"] for p in listed] == [plan_id]
    assert listed[0]["visit_frequency_rule"] == {"rrule": "FREQ=DAILY;COUNT=2", "start_hour": 9}

    # A second plan sorts ahead of the first, because the screen offers the newest by default.
    later_plan = await client.post(
        f"/v1/clients/{client_id}/care-plans",
        headers=headers,
        json={
            "authorized_tasks": [{"code": "meal_prep", "label": "Meal preparation"}],
            "visit_frequency_rule": {"rrule": "FREQ=WEEKLY;BYDAY=SA,SU", "start_hour": 14},
            "effective_start": (datetime.now(UTC) + timedelta(days=30)).date().isoformat(),
        },
    )
    assert later_plan.status_code == 201, later_plan.text
    ordered = (await client.get(f"/v1/clients/{client_id}/care-plans", headers=headers)).json()
    assert [p["id"] for p in ordered] == [later_plan.json()["id"], plan_id]

    # 4. Generate visits.
    generate = await client.post(
        f"/v1/care-plans/{plan_id}/generate-visits",
        headers=headers,
        json={
            "window_start": datetime.now(UTC).date().isoformat(),
            "window_end": (datetime.now(UTC) + timedelta(days=7)).date().isoformat(),
            "duration_minutes": 60,
        },
    )
    assert generate.status_code == 201, generate.text
    visits = generate.json()
    assert len(visits) == 2
    visit_id = visits[0]["id"]
    assert visits[0]["status"] == "open"

    # 5. Add a caregiver. They start unscreened.
    caregiver_response = await client.post(
        "/v1/caregivers",
        headers=headers,
        json={"legal_name": "Grace Caregiver", "geo_lat": 40.7128, "geo_lng": -74.0060},
    )
    assert caregiver_response.status_code == 201
    caregiver = caregiver_response.json()
    caregiver_id = caregiver["id"]
    assert caregiver["exclusion_check_status"] == "not_run"

    # 6. Assigning before the exclusion check clears must be refused (US-1.3.2).
    blocked = await client.post(
        f"/v1/visits/{visit_id}/assign", headers=headers, json={"caregiver_id": caregiver_id}
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "COMPLIANCE_GATE_FAILED"

    # 7. Record the exclusion screening result.
    cleared = await client.post(
        f"/v1/caregivers/{caregiver_id}/exclusion-check",
        headers={**headers, "Idempotency-Key": f"excl-{unique}"},
        json={"status": "cleared", "vendor_key": "test_vendor", "vendor_reference": "ref-1"},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["exclusion_check_status"] == "cleared"
    assert cleared.json()["exclusion_checked_at"] is not None

    # 8. Now the assignment succeeds.
    assigned = await client.post(
        f"/v1/visits/{visit_id}/assign", headers=headers, json={"caregiver_id": caregiver_id}
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["status"] == "assigned"

    # 9. Clock in.
    now = datetime.now(UTC)
    clock_in = await client.post(
        f"/v1/visits/{visit_id}/clock-in",
        headers={**headers, "Idempotency-Key": f"ci-{unique}"},
        json={
            "timestamp": now.isoformat(),
            "capture_method": "mobile_gps",
            "geo": {"lat": 40.7128, "lng": -74.0060},
            "client_local_uuid": f"offline-{unique}",
        },
    )
    assert clock_in.status_code == 201, clock_in.text
    evv = clock_in.json()
    assert evv["transmission_status"] == "pending"
    assert evv["is_compliant"] is False, "not compliant until the aggregator acknowledges"

    # 10. Clock out, receiving compliance findings alongside success.
    clock_out = await client.post(
        f"/v1/visits/{visit_id}/clock-out",
        headers={**headers, "Idempotency-Key": f"co-{unique}"},
        json={
            "timestamp": (now + timedelta(hours=1)).isoformat(),
            "geo": {"lat": 40.7128, "lng": -74.0060},
            "client_local_uuid": f"offline-{unique}",
        },
    )
    assert clock_out.status_code == 200, clock_out.text
    body = clock_out.json()
    assert body["evv"]["clock_out_time"] is not None

    # The visit is complete but untransmitted, so exactly that is flagged — and nothing
    # about it blocked the caregiver from finishing.
    flagged = {f["rule_key"] for f in body["compliance_findings"]}
    assert "evv.transmission_unacknowledged" in flagged

    # 11. EVV status is readable.
    status = await client.get(f"/v1/visits/{visit_id}/evv-status", headers=headers)
    assert status.status_code == 200
    assert status.json()["capture_method"] == "mobile_gps"


async def test_error_envelope_shape(client) -> None:
    """Every error uses the single envelope from `05_API_Specification.md` Section 1."""
    response = await client.post("/v1/auth/login", json={"email": "nobody@test", "password": "x"})
    assert response.status_code == 401
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}


async def test_validation_errors_use_the_same_envelope(client, tenant_a: TenantFixture) -> None:
    """FastAPI's default 422 body is re-shaped so clients parse one format."""
    response = await client.post(
        "/v1/clients",
        headers=tenant_a.headers(),
        json={"legal_name": "Missing required fields"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "errors" in body["error"]["details"]


async def test_invalid_state_code_is_rejected(client) -> None:
    response = await client.post(
        "/v1/agencies",
        json={
            "legal_name": "Bad State",
            "service_states": ["NEW YORK"],
            "service_lines": ["home_care"],
            "accepted_payer_types": ["private_pay"],
            "owner_email": "x@example.com",
            "owner_password": "a-sufficiently-long-password",
        },
    )
    assert response.status_code == 422


async def test_duplicate_owner_email_is_refused(client) -> None:
    unique = uuid.uuid4().hex[:8]
    payload = {
        "legal_name": "First Agency",
        "service_states": ["NY"],
        "service_lines": ["home_care"],
        "accepted_payer_types": ["private_pay"],
        "owner_email": f"dupe-{unique}@example.com",
        "owner_password": "a-sufficiently-long-password",
    }
    assert (await client.post("/v1/agencies", json=payload)).status_code == 201
    second = await client.post("/v1/agencies", json={**payload, "legal_name": "Second Agency"})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CONFLICT"


async def test_login_does_not_reveal_whether_an_account_exists(client) -> None:
    """Same response for an unknown email and a wrong password."""
    unknown = await client.post(
        "/v1/auth/login", json={"email": "no-such-user@example.com", "password": "whatever"}
    )
    unique = uuid.uuid4().hex[:8]
    await client.post(
        "/v1/agencies",
        json={
            "legal_name": "Probe Agency",
            "service_states": ["NY"],
            "service_lines": ["home_care"],
            "accepted_payer_types": ["private_pay"],
            "owner_email": f"probe-{unique}@example.com",
            "owner_password": "a-sufficiently-long-password",
        },
    )
    wrong_password = await client.post(
        "/v1/auth/login",
        json={"email": f"probe-{unique}@example.com", "password": "definitely-wrong"},
    )

    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json()


async def test_caregiver_sees_only_their_own_visits(
    client, tenant_a: TenantFixture, reference_data: None
) -> None:
    """Minimum-necessary access: a caregiver is not shown the agency's whole schedule."""
    from careos.db.session import tenant_session
    from careos.modules.credentialing.models import Caregiver
    from careos.modules.scheduling import service as scheduling
    from careos.modules.scheduling.models import CarePlan
    from tests.conftest import make_client_with_plan

    _client_id, plan_id = await make_client_with_plan(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        plan = await session.get(CarePlan, plan_id)
        visits = await scheduling.generate_visits(
            session,
            principal=tenant_a.principal(),
            care_plan=plan,
            window=scheduling.GenerationWindow(
                start=datetime.now(UTC).date(),
                end=(datetime.now(UTC) + timedelta(days=7)).date(),
            ),
            duration_minutes=60,
        )
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        # Assign only the first of three visits to this caregiver.
        await scheduling.assign_caregiver(
            session, principal=tenant_a.principal(), visit=visits[0], caregiver=caregiver
        )
        assigned_id = str(visits[0].id)
        unassigned_id = str(visits[1].id)

    as_caregiver = await client.get("/v1/visits", headers=tenant_a.headers(Role.caregiver))
    assert as_caregiver.status_code == 200
    returned = {v["id"] for v in as_caregiver.json()["items"]}
    assert returned == {assigned_id}

    # And a direct fetch of someone else's visit is refused, not merely hidden from the list.
    direct = await client.get(
        f"/v1/visits/{unassigned_id}", headers=tenant_a.headers(Role.caregiver)
    )
    assert direct.status_code == 403


async def test_scheduler_sees_all_agency_visits(
    client, tenant_a: TenantFixture, reference_data: None
) -> None:
    from careos.db.session import tenant_session
    from careos.modules.scheduling import service as scheduling
    from careos.modules.scheduling.models import CarePlan
    from tests.conftest import make_client_with_plan

    _client_id, plan_id = await make_client_with_plan(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        plan = await session.get(CarePlan, plan_id)
        await scheduling.generate_visits(
            session,
            principal=tenant_a.principal(),
            care_plan=plan,
            window=scheduling.GenerationWindow(
                start=datetime.now(UTC).date(),
                end=(datetime.now(UTC) + timedelta(days=7)).date(),
            ),
            duration_minutes=60,
        )

    response = await client.get("/v1/visits", headers=tenant_a.headers(Role.scheduler))
    assert response.status_code == 200
    assert response.json()["page"]["total"] == 3


async def test_health_endpoint_needs_no_auth(client) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_request_id_is_echoed(client) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "test-request-id"})
    assert response.headers["X-Request-ID"] == "test-request-id"
