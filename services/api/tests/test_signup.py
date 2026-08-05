"""Public self-serve sign-up (`05_API_Specification.md` Section 2, PRD US-1.1.1).

`POST /v1/agencies` existed from the first increment and nothing could reach it: there was no
sign-up screen anywhere, so the only way to create a tenant was a `curl`. The endpoint is
unchanged in shape; what these tests pin is the contract the admin console's wizard now
depends on, and the boundaries that make a public tenant-creating endpoint defensible.

The rate-limit half lives in `test_rate_limits.py`, which owns the limiter's fixtures.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from careos.core.security import decode_token
from careos.db.session import tenant_session
from careos.modules.agency.models import Agency, AgencyStatus, AppUser, Role, UserStatus
from careos.modules.audit.models import AuditLog
from careos.modules.scheduling.models import Client


def _signup_body(**overrides: object) -> dict[str, object]:
    suffix = uuid.uuid4().hex[:8]
    body: dict[str, object] = {
        "legal_name": f"Harbour Home Care {suffix}",
        "service_states": ["ny"],
        "service_lines": ["home_care"],
        "accepted_payer_types": ["medicaid_waiver", "private_pay"],
        "owner_email": f"owner-{suffix}@harbourcare.example",
        "owner_password": "a-sufficiently-long-password",
    }
    body.update(overrides)
    return body


async def test_signing_up_creates_a_tenant_and_a_working_owner_login(client) -> None:
    """The whole flow the wizard drives, end to end against a real database."""
    body = _signup_body()
    created = await client.post("/v1/agencies", json=body)
    assert created.status_code == 201

    agency = created.json()
    assert agency["legal_name"] == body["legal_name"]
    # Normalized on the way in, so a lower-case state code from a form still selects the EVV
    # adapter — the whole reason this field is validated rather than free text.
    assert agency["service_states"] == ["NY"]
    # A brand-new tenant is active. There is no approval step, and pretending otherwise by
    # defaulting to suspended would make the sign-up screen a lie.
    assert agency["status"] == "active"

    signed_in = await client.post(
        "/v1/auth/login",
        json={"email": body["owner_email"], "password": body["owner_password"]},
    )
    assert signed_in.status_code == 200

    headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}
    me = await client.get("/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["role"] == "owner_admin"
    assert me.json()["status"] == "active"
    # Not yet enrolled, which is correct: `owner_admin` is an MFA-required role, and the
    # session they hold is the one that can reach the enrolment endpoints.
    assert me.json()["mfa_enrolled"] is False


async def test_a_new_tenant_starts_empty_and_cannot_see_its_neighbour(client) -> None:
    """Two agencies signed up minutes apart must be as isolated as any other pair."""
    first_body = _signup_body()
    second_body = _signup_body()
    first = await client.post("/v1/agencies", json=first_body)
    second = await client.post("/v1/agencies", json=second_body)
    assert first.status_code == 201 and second.status_code == 201

    signed_in = await client.post(
        "/v1/auth/login",
        json={"email": first_body["owner_email"], "password": first_body["owner_password"]},
    )
    headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}

    clients = await client.get("/v1/clients", headers=headers)
    assert clients.status_code == 200
    assert clients.json() == []

    users = await client.get(f"/v1/agencies/{first.json()['id']}/users", headers=headers)
    assert len(users.json()) == 1

    # And the neighbour is out of reach by path, exactly as for any other pair of tenants.
    neighbour = await client.get(f"/v1/agencies/{second.json()['id']}", headers=headers)
    assert neighbour.status_code == 403


async def test_signup_creates_exactly_one_owner_admin_and_no_other_role(client) -> None:
    """Sign-up is not a route around the invite flow or around RBAC."""
    created = await client.post("/v1/agencies", json=_signup_body())
    agency_id = uuid.UUID(created.json()["id"])

    async with tenant_session(agency_id) as session:
        users = (await session.execute(select(AppUser))).scalars().all()
    assert len(users) == 1
    assert users[0].role is Role.owner_admin
    assert users[0].status is UserStatus.active
    # A password hash, never the password.
    assert users[0].password_hash is not None
    assert "a-sufficiently-long-password" not in users[0].password_hash


async def test_signup_writes_an_audit_row_attributed_to_the_owner(client) -> None:
    """There is no prior user to attribute the tenant's creation to, so the owner is the actor.

    An unattributed row would break the trail's continuity at exactly the point an auditor
    starts reading it.
    """
    created = await client.post("/v1/agencies", json=_signup_body())
    agency_id = uuid.UUID(created.json()["id"])

    async with tenant_session(agency_id) as session:
        rows = (
            await session.execute(select(AuditLog).where(AuditLog.action == "agency.created"))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].actor_user_id is not None
    assert rows[0].agency_id == agency_id


async def test_a_second_signup_with_the_same_email_is_refused(client) -> None:
    """Email uniqueness is what makes a double-submitted form safe.

    It is also why this endpoint needs no `Idempotency-Key`: the natural key is already
    unique, and a replay produces a 409 rather than a second tenant. The trade-off is
    account enumeration on a public endpoint, which is stated in BUILD_STATUS rather than
    hidden — the sign-up limiter is what bounds it.
    """
    body = _signup_body()
    assert (await client.post("/v1/agencies", json=body)).status_code == 201

    duplicate_body = _signup_body(owner_email=body["owner_email"])
    duplicate = await client.post("/v1/agencies", json=duplicate_body)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "CONFLICT"

    # The refused attempt left no half-built tenant behind: the owner still signs in to the
    # first agency, under the first legal name.
    signed_in = await client.post(
        "/v1/auth/login",
        json={"email": body["owner_email"], "password": body["owner_password"]},
    )
    assert signed_in.status_code == 200
    headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}
    me = await client.get("/v1/auth/me", headers=headers)
    agency = await client.get(
        f"/v1/agencies/{_agency_id_from_token(signed_in.json()['access_token'])}",
        headers=headers,
    )
    assert me.status_code == 200
    assert agency.json()["legal_name"] == body["legal_name"]


async def test_a_short_password_is_refused_with_the_standard_envelope(client) -> None:
    response = await client.post("/v1/agencies", json=_signup_body(owner_password="short"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_an_unrecognisable_state_code_is_refused(client) -> None:
    """The state code selects the EVV adapter, so it is validated rather than accepted."""
    response = await client.post("/v1/agencies", json=_signup_body(service_states=["New York"]))
    assert response.status_code == 422


async def test_at_least_one_service_state_line_and_payer_is_required(client) -> None:
    """Each of the three drives compliance behaviour, so none of them is deferrable.

    An agency with no service state has no EVV aggregator, no compliance rule set, and cannot
    create a client. Collecting them at sign-up is three choices; discovering them missing is
    a support call on the first day.
    """
    for field in ("service_states", "service_lines", "accepted_payer_types"):
        response = await client.post("/v1/agencies", json=_signup_body(**{field: []}))
        assert response.status_code == 422, field


async def test_signup_cannot_set_a_tenants_ranking_display(client) -> None:
    """A new agency is in the ranking shadow period by construction, not by remembering."""
    created = await client.post(
        "/v1/agencies", json=_signup_body(ranking_display_enabled=True)
    )
    assert created.status_code == 201

    agency_id = uuid.UUID(created.json()["id"])
    async with tenant_session(agency_id) as session:
        agency = await session.get(Agency, agency_id)
        assert agency is not None
        assert agency.ranking_display_enabled is False
        assert agency.status is AgencyStatus.active


async def test_signup_cannot_smuggle_rows_into_another_tenant(client) -> None:
    """No request model accepts an `agency_id`, and this is the one endpoint with no token.

    Worth pinning explicitly: a public endpoint that creates a tenant is the natural place to
    try to attach something to an existing one.
    """
    first = await client.post("/v1/agencies", json=_signup_body())
    victim_id = uuid.UUID(first.json()["id"])

    attacker = await client.post(
        "/v1/agencies", json=_signup_body(agency_id=str(victim_id), id=str(victim_id))
    )
    assert attacker.status_code == 201
    assert attacker.json()["id"] != str(victim_id)

    async with tenant_session(victim_id) as session:
        assert (await session.execute(select(Client))).scalars().all() == []
        assert len((await session.execute(select(AppUser))).scalars().all()) == 1


def _agency_id_from_token(token: str) -> uuid.UUID:
    """The tenant the token was minted for, which is the only place a client may learn it."""
    return decode_token(token).agency_id
