"""Audit trail and idempotency tests.

Both are cross-cutting infrastructure (`08_Security_Architecture.md` Section 4,
`05_API_Specification.md` Section 1) rather than features, so they are tested on their own
terms as well as through the flows that use them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from careos.core.audit import AuditAction, diff_state, record_audit
from careos.core.errors import ConflictError, IdempotencyKeyRequiredError
from careos.core.idempotency import claim, complete, hash_request
from careos.db.session import tenant_session
from careos.modules.agency.models import Role
from careos.modules.audit.models import AuditLog
from careos.modules.scheduling.models import CarePlan
from tests.conftest import TenantFixture, make_client_with_plan

# --- Audit trail --------------------------------------------------------------------------


async def test_audit_row_is_written_in_the_callers_transaction(
    tenant_a: TenantFixture,
) -> None:
    """A rolled-back change must not leave an audit row claiming it happened."""
    async with tenant_session(tenant_a.agency_id) as session:
        await record_audit(
            session,
            principal=tenant_a.principal(),
            agency_id=tenant_a.agency_id,
            action=AuditAction.client_created,
            entity_type="client",
            entity_id=uuid.uuid4(),
        )
        await session.rollback()

    async with tenant_session(tenant_a.agency_id) as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
        assert rows == [], "an audit row survived a rolled-back transaction"


async def test_phi_reads_are_audited(client, tenant_a: TenantFixture) -> None:
    """HIPAA's audit-control requirement covers reads, not only writes."""
    from careos.db.session import tenant_session as ts
    from careos.modules.scheduling.models import Client

    async with ts(tenant_a.agency_id) as session:
        record = Client(
            agency_id=tenant_a.agency_id,
            legal_name="Viewed Client",
            service_state="NY",
            primary_payer_type="private_pay",
        )
        session.add(record)
        await session.flush()
        client_id = record.id

    response = await client.get(f"/v1/clients/{client_id}", headers=tenant_a.headers())
    assert response.status_code == 200

    async with ts(tenant_a.agency_id) as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == AuditAction.client_viewed.value)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].is_phi_access is True
    assert rows[0].entity_id == client_id


async def test_audit_records_actor_and_request_context(client, tenant_a: TenantFixture) -> None:
    response = await client.post(
        "/v1/clients",
        headers={**tenant_a.headers(), "X-Request-ID": "req-abc-123"},
        json={
            "legal_name": "Audited Client",
            "service_state": "NY",
            "primary_payer_type": "private_pay",
        },
    )
    assert response.status_code == 201

    async with tenant_session(tenant_a.agency_id) as session:
        row = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == AuditAction.client_created.value)
            )
        ).scalar_one()
    assert row.actor_user_id == tenant_a.owner_id
    assert row.request_id == "req-abc-123"
    assert row.agency_id == tenant_a.agency_id


async def test_role_change_records_before_and_after(client, tenant_a: TenantFixture) -> None:
    invite = await client.post(
        f"/v1/agencies/{tenant_a.agency_id}/users",
        headers=tenant_a.headers(),
        json={
            "email": f"scheduler-{uuid.uuid4().hex[:8]}@example.com",
            "role": "scheduler",
            "initial_password": "another-long-enough-password",
        },
    )
    assert invite.status_code == 201
    user_id = invite.json()["id"]

    changed = await client.patch(
        f"/v1/users/{user_id}/role", headers=tenant_a.headers(), json={"role": "auditor"}
    )
    assert changed.status_code == 200

    async with tenant_session(tenant_a.agency_id) as session:
        row = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == AuditAction.user_role_changed.value)
            )
        ).scalar_one()
    assert row.before_state == {"role": "scheduler"}
    assert row.after_state == {"role": "auditor"}


async def test_failed_login_is_audited(client, tenant_a: TenantFixture) -> None:
    unique = uuid.uuid4().hex[:8]
    email = f"loginaudit-{unique}@example.com"
    await client.post(
        f"/v1/agencies/{tenant_a.agency_id}/users",
        headers=tenant_a.headers(),
        json={"email": email, "role": "scheduler", "initial_password": "long-enough-password-x"},
    )

    bad = await client.post("/v1/auth/login", json={"email": email, "password": "wrong"})
    assert bad.status_code == 401

    async with tenant_session(tenant_a.agency_id) as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == AuditAction.user_login_failed.value)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].actor_user_id is None, "a failed login has no established actor"


def test_diff_state_reports_only_changes() -> None:
    diff = diff_state({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 99, "d": 4})
    assert diff == {
        "b": {"before": 2, "after": 99},
        "c": {"before": 3, "after": None},
        "d": {"before": None, "after": 4},
    }


# --- Idempotency --------------------------------------------------------------------------


def test_request_hash_is_key_order_independent() -> None:
    assert hash_request({"a": 1, "b": 2}) == hash_request({"b": 2, "a": 1})


def test_request_hash_differs_on_different_content() -> None:
    assert hash_request({"a": 1}) != hash_request({"a": 2})


async def test_missing_idempotency_key_is_rejected(tenant_a: TenantFixture) -> None:
    async with tenant_session(tenant_a.agency_id) as session:
        with pytest.raises(IdempotencyKeyRequiredError):
            await claim(
                session,
                principal=tenant_a.principal(),
                key=None,
                endpoint="test.endpoint",
                payload={"a": 1},
            )


async def test_replay_with_same_key_and_body_returns_stored_response(
    tenant_a: TenantFixture,
) -> None:
    async with tenant_session(tenant_a.agency_id) as session:
        first = await claim(
            session,
            principal=tenant_a.principal(),
            key="k1",
            endpoint="test.endpoint",
            payload={"a": 1},
        )
        assert not first.is_replay
        await complete(session, first.record, status=201, body={"result": "created"})

        second = await claim(
            session,
            principal=tenant_a.principal(),
            key="k1",
            endpoint="test.endpoint",
            payload={"a": 1},
        )
    assert second.is_replay
    assert second.replayed_status == 201
    assert second.replayed_body == {"result": "created"}


async def test_same_key_with_different_body_is_a_conflict(tenant_a: TenantFixture) -> None:
    """Returning the first response would silently discard the second request."""
    async with tenant_session(tenant_a.agency_id) as session:
        first = await claim(
            session,
            principal=tenant_a.principal(),
            key="k2",
            endpoint="test.endpoint",
            payload={"a": 1},
        )
        await complete(session, first.record, status=200, body={"ok": True})

        with pytest.raises(ConflictError, match="different request body"):
            await claim(
                session,
                principal=tenant_a.principal(),
                key="k2",
                endpoint="test.endpoint",
                payload={"a": 999},
            )


async def test_in_flight_replay_is_a_conflict(tenant_a: TenantFixture) -> None:
    async with tenant_session(tenant_a.agency_id) as session:
        await claim(
            session,
            principal=tenant_a.principal(),
            key="k3",
            endpoint="test.endpoint",
            payload={"a": 1},
        )
        with pytest.raises(ConflictError, match="still in progress"):
            await claim(
                session,
                principal=tenant_a.principal(),
                key="k3",
                endpoint="test.endpoint",
                payload={"a": 1},
            )


async def test_same_key_on_a_different_endpoint_is_independent(
    tenant_a: TenantFixture,
) -> None:
    async with tenant_session(tenant_a.agency_id) as session:
        first = await claim(
            session,
            principal=tenant_a.principal(),
            key="shared",
            endpoint="endpoint.one",
            payload={"a": 1},
        )
        second = await claim(
            session,
            principal=tenant_a.principal(),
            key="shared",
            endpoint="endpoint.two",
            payload={"a": 1},
        )
    assert not first.is_replay
    assert not second.is_replay


async def test_idempotency_keys_are_scoped_per_tenant(
    tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    """One agency's key must not collide with another's."""
    async with tenant_session(tenant_a.agency_id) as session:
        a_claim = await claim(
            session,
            principal=tenant_a.principal(),
            key="same-key",
            endpoint="test.endpoint",
            payload={"a": 1},
        )
        await complete(session, a_claim.record, status=200, body={"tenant": "a"})

    async with tenant_session(tenant_b.agency_id) as session:
        b_claim = await claim(
            session,
            principal=tenant_b.principal(),
            key="same-key",
            endpoint="test.endpoint",
            payload={"a": 1},
        )
    assert not b_claim.is_replay, "Tenant B replayed Tenant A's response"


async def test_clock_in_requires_idempotency_key(
    client, tenant_a: TenantFixture, reference_data: None
) -> None:
    """The endpoint has external side effects, so the header is mandatory."""
    from careos.modules.scheduling import service as scheduling

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
        visit_id = visits[0].id

    response = await client.post(
        f"/v1/visits/{visit_id}/clock-in",
        headers=tenant_a.headers(Role.scheduler),
        json={"timestamp": datetime.now(UTC).isoformat(), "capture_method": "mobile_gps"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
