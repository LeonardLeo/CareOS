"""Session revocation and caregiver offboarding.

`08_Security_Architecture.md` Section 6 requires an agency admin to be able to immediately cut
off a terminated caregiver, *including any offline-cached PHI on their device*. Nothing enforced
that before this: the caregiver app cleared its cache when the API rejected a token, and the API
had no way to reject one.

The tests that matter here are the ones proving a token stops working — a revocation feature
that returns 200 while the old token keeps reading client addresses is worse than none, because
it produces a record saying access was removed when it was not.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from careos.db.session import tenant_session
from careos.modules.agency.models import AppUser, Role
from careos.modules.audit.models import AuditLog
from careos.modules.credentialing.models import Caregiver, EmploymentStatus, ExclusionCheckStatus
from tests.conftest import TenantFixture


async def _login(client, email: str, password: str) -> str:
    response = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _invite(client, tenant: TenantFixture, role: str, password: str) -> tuple[str, str]:
    """Invite a user and return (user_id, email)."""
    email = f"{role}-{uuid.uuid4().hex[:8]}@offboarding.example.com"
    response = await client.post(
        f"/v1/agencies/{tenant.agency_id}/users",
        headers=tenant.headers(Role.owner_admin),
        json={"email": email, "role": role, "initial_password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], email


async def test_revoking_sessions_stops_an_existing_token_working(
    client, tenant_a: TenantFixture
) -> None:
    """The whole point. A token that worked a moment ago must stop working.

    Not asserted via the revoke endpoint's own response — that only proves the write happened.
    The same token is replayed against a PHI-bearing endpoint before and after.
    """
    password = "a-sufficiently-long-password"
    user_id, email = await _invite(client, tenant_a, "scheduler", password)
    token = await _login(client, email, password)
    headers = {"Authorization": f"Bearer {token}"}

    before = await client.get("/v1/clients", headers=headers)
    assert before.status_code == 200

    revoke = await client.post(
        f"/v1/users/{user_id}/revoke-sessions",
        headers=tenant_a.headers(Role.owner_admin),
        json={"reason": "left the agency"},
    )
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["sessions_revoked_at"] is not None

    after = await client.get("/v1/clients", headers=headers)
    assert after.status_code == 401
    assert "administrator" in after.json()["error"]["message"]


async def test_a_fresh_login_works_after_revocation(client, tenant_a: TenantFixture) -> None:
    """Revocation ends sessions; it does not disable the account.

    That distinction matters operationally: a lost phone needs every session killed while the
    caregiver keeps working from a replacement, and a suspension pending investigation is not a
    termination.
    """
    password = "a-sufficiently-long-password"
    user_id, email = await _invite(client, tenant_a, "scheduler", password)
    old_token = await _login(client, email, password)

    await client.post(
        f"/v1/users/{user_id}/revoke-sessions",
        headers=tenant_a.headers(Role.owner_admin),
        json={"reason": "lost phone"},
    )
    assert (
        await client.get("/v1/clients", headers={"Authorization": f"Bearer {old_token}"})
    ).status_code == 401

    new_token = await _login(client, email, password)
    assert (
        await client.get("/v1/clients", headers={"Authorization": f"Bearer {new_token}"})
    ).status_code == 200


async def test_revocation_only_affects_the_named_user(client, tenant_a: TenantFixture) -> None:
    """A colleague's session must survive — otherwise offboarding one person logs out the shift."""
    password = "a-sufficiently-long-password"
    target_id, target_email = await _invite(client, tenant_a, "scheduler", password)
    _other_id, other_email = await _invite(client, tenant_a, "clinical_supervisor", password)

    target_token = await _login(client, target_email, password)
    other_token = await _login(client, other_email, password)

    await client.post(
        f"/v1/users/{target_id}/revoke-sessions",
        headers=tenant_a.headers(Role.owner_admin),
        json={"reason": "offboarded"},
    )

    assert (
        await client.get("/v1/clients", headers={"Authorization": f"Bearer {target_token}"})
    ).status_code == 401
    assert (
        await client.get("/v1/clients", headers={"Authorization": f"Bearer {other_token}"})
    ).status_code == 200


async def test_only_an_owner_admin_can_revoke(client, tenant_a: TenantFixture) -> None:
    for role in (Role.scheduler, Role.clinical_supervisor, Role.auditor, Role.caregiver):
        response = await client.post(
            f"/v1/users/{tenant_a.owner_id}/revoke-sessions",
            headers=tenant_a.headers(role),
            json={"reason": "should not be permitted"},
        )
        assert response.status_code == 403, f"{role} must not be able to revoke sessions"


async def test_revocation_requires_a_reason(client, tenant_a: TenantFixture) -> None:
    """The reason is the evidence. An audit asks why access was removed, not just when."""
    response = await client.post(
        f"/v1/users/{tenant_a.owner_id}/revoke-sessions",
        headers=tenant_a.headers(Role.owner_admin),
        json={},
    )
    assert response.status_code == 422


async def test_revocation_is_audited_with_its_reason(client, tenant_a: TenantFixture) -> None:
    user_id, _email = await _invite(client, tenant_a, "scheduler", "a-sufficiently-long-password")
    await client.post(
        f"/v1/users/{user_id}/revoke-sessions",
        headers=tenant_a.headers(Role.owner_admin),
        json={"reason": "resigned on 2026-07-30"},
    )

    async with tenant_session(tenant_a.agency_id) as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "user.sessions_revoked")
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].entity_id == uuid.UUID(user_id)
    assert rows[0].after_state["reason"] == "resigned on 2026-07-30"


async def test_a_token_for_a_deleted_user_is_refused(client, tenant_a: TenantFixture) -> None:
    """A token whose user no longer exists must not authenticate.

    Before the revocation check existed, authentication was pure signature verification, so a
    token outlived the account it named for the rest of its TTL.
    """
    from careos.core.security import create_token

    token = create_token(
        user_id=uuid.uuid4(),  # never existed
        agency_id=tenant_a.agency_id,
        role=Role.owner_admin,
        token_type="access",
    )
    response = await client.get("/v1/clients", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "no longer active" in response.json()["error"]["message"]


# --- Caregiver termination ------------------------------------------------------------------


async def _caregiver_with_login(
    client, tenant: TenantFixture, password: str
) -> tuple[str, str, str]:
    """Create a caregiver linked to their own login. Returns (caregiver_id, user_id, email)."""
    user_id, email = await _invite(client, tenant, "caregiver", password)
    created = await client.post(
        "/v1/caregivers",
        headers=tenant.headers(Role.owner_admin),
        json={"legal_name": "Grace Caregiver", "app_user_id": user_id},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"], user_id, email


async def test_terminating_a_caregiver_cuts_off_their_access(
    client, tenant_a: TenantFixture
) -> None:
    """Termination and revocation are one operation, not two an admin must remember.

    This is the requirement in `08_Security_Architecture.md` Section 6 stated as a test: after
    offboarding, the caregiver's own token can no longer reach their schedule — which is what
    makes the app drop the client names and addresses it had cached.
    """
    password = "a-sufficiently-long-password"
    caregiver_id, _user_id, email = await _caregiver_with_login(client, tenant_a, password)
    token = await _login(client, email, password)
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/v1/my-visits", headers=headers)).status_code == 200

    terminated = await client.post(
        f"/v1/caregivers/{caregiver_id}/terminate",
        headers=tenant_a.headers(Role.owner_admin),
        json={"reason": "resigned"},
    )
    assert terminated.status_code == 200, terminated.text
    assert terminated.json()["employment_status"] == "terminated"

    denied = await client.get("/v1/my-visits", headers=headers)
    assert denied.status_code == 401


async def test_terminating_records_both_the_status_and_the_revocation(
    client, tenant_a: TenantFixture
) -> None:
    password = "a-sufficiently-long-password"
    caregiver_id, user_id, _email = await _caregiver_with_login(client, tenant_a, password)

    await client.post(
        f"/v1/caregivers/{caregiver_id}/terminate",
        headers=tenant_a.headers(Role.owner_admin),
        json={"reason": "gross misconduct"},
    )

    async with tenant_session(tenant_a.agency_id) as session:
        actions = set(
            (await session.execute(select(AuditLog.action))).scalars().all()  # type: ignore[arg-type]
        )
        termination = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "caregiver.terminated")
                )
            )
            .scalars()
            .one()
        )
        user = await session.get(AppUser, uuid.UUID(user_id))

    # Both events, not one standing in for the other.
    assert "caregiver.terminated" in actions
    assert "user.sessions_revoked" in actions
    assert termination.after_state["revoked_app_user_id"] == user_id
    assert termination.after_state["reason"] == "gross misconduct"
    assert user is not None and user.sessions_revoked_at is not None


async def test_terminating_a_caregiver_with_no_login_still_succeeds(
    client, tenant_a: TenantFixture
) -> None:
    """Not every caregiver has an app account — a telephony-only worker may have none.

    Termination must not fail for them, and the audit trail should say plainly that there was
    no login to revoke rather than leaving it ambiguous.
    """
    created = await client.post(
        "/v1/caregivers",
        headers=tenant_a.headers(Role.owner_admin),
        json={"legal_name": "No Login Caregiver"},
    )
    assert created.status_code == 201
    caregiver_id = created.json()["id"]

    response = await client.post(
        f"/v1/caregivers/{caregiver_id}/terminate",
        headers=tenant_a.headers(Role.owner_admin),
        json={"reason": "contract ended"},
    )
    assert response.status_code == 200
    assert response.json()["employment_status"] == "terminated"

    async with tenant_session(tenant_a.agency_id) as session:
        termination = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "caregiver.terminated")
                )
            )
            .scalars()
            .one()
        )
    assert termination.after_state["revoked_app_user_id"] is None


async def test_a_terminated_caregiver_cannot_be_assigned_a_visit(
    client, tenant_a: TenantFixture
) -> None:
    """Offboarding has to remove someone from scheduling, not just from logging in."""
    from careos.modules.scheduling import service as scheduling
    from careos.modules.scheduling.models import CarePlan
    from tests.conftest import make_client_with_plan

    _client_id, plan_id = await make_client_with_plan(tenant_a)
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date()
    async with tenant_session(tenant_a.agency_id) as session:
        plan = await session.get(CarePlan, plan_id)
        assert plan is not None
        visits = await scheduling.generate_visits(
            session,
            principal=tenant_a.principal(),
            care_plan=plan,
            window=scheduling.GenerationWindow(start=tomorrow, end=tomorrow + timedelta(days=1)),
            duration_minutes=60,
        )
        visit_id = visits[0].id

        caregiver = Caregiver(
            agency_id=tenant_a.agency_id,
            legal_name="Soon Terminated",
            employment_status=EmploymentStatus.active,
            exclusion_check_status=ExclusionCheckStatus.cleared,
            exclusion_checked_at=datetime.now(UTC),
        )
        session.add(caregiver)
        await session.flush()
        caregiver_id = caregiver.id

    await client.post(
        f"/v1/caregivers/{caregiver_id}/terminate",
        headers=tenant_a.headers(Role.owner_admin),
        json={"reason": "offboarded"},
    )

    response = await client.post(
        f"/v1/visits/{visit_id}/assign",
        headers=tenant_a.headers(Role.owner_admin),
        json={"caregiver_id": str(caregiver_id)},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "COMPLIANCE_GATE_FAILED"
