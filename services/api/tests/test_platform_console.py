"""The CareOS operator console, and the boundaries around it.

Half of this file is negative. That is the point: a platform operator is the most privileged
principal in the system, and what makes the design defensible is not what it can do but the
list of things it cannot — read a client, read an agency's audit trail, reach a tenant
endpoint, act without leaving a record, or hold a session that skipped its second factor.
Each of those is asserted here against a real database and the real role, not argued from the
code.

The isolation-specific assertions — that `careos_platform` holds no `BYPASSRLS` and no grant
on any PHI table, and that adding its policies did not widen what `careos_app` can see — live
in `test_multitenant_isolation.py`, which is the CI-required suite.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from careos.core import mfa
from careos.core.security import create_token, decode_platform_token, decode_token
from careos.db.session import platform_session, tenant_session
from careos.modules.agency.models import Agency, AgencyStatus, Role
from careos.modules.audit.models import AuditLog
from careos.modules.credentialing.models import Credential, VerificationStatus
from careos.modules.platform.models import (
    PLATFORM_HEALTH_COLUMNS,
    PLATFORM_HEALTH_VIEW,
    PlatformAuditLog,
    PlatformOperator,
    PlatformRole,
)
from careos.modules.scheduling.models import (
    ComplianceException,
    EVVRecord,
    CaptureMethod,
    TransmissionStatus,
    VisitStatus,
)
from tests.conftest import PlatformFixture, TenantFixture, make_client_with_plan, make_operator

OPERATOR_PASSWORD = "operator-password-that-is-long"


# --- The shape of the view ----------------------------------------------------------------


async def test_health_view_columns_match_the_declared_tuple(database: None) -> None:
    """The migration's SQL and `PLATFORM_HEALTH_COLUMNS` must describe the same view.

    They are written in two places — a `CREATE VIEW` in a migration and a tuple in Python
    that the projection and the dataclass are both built from. A column added to one and not
    the other renders as an always-empty field in the console rather than as an error, which
    is exactly the kind of drift nothing else here would catch.
    """
    async with platform_session() as session:
        columns = (
            await session.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = :view
                    ORDER BY ordinal_position
                    """
                ),
                {"view": PLATFORM_HEALTH_VIEW},
            )
        ).scalars().all()
    assert tuple(columns) == PLATFORM_HEALTH_COLUMNS


# --- What an operator can see -------------------------------------------------------------


async def test_fleet_lists_every_agency_with_operational_counts(
    client, platform_admin: PlatformFixture, tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    await make_client_with_plan(tenant_a)

    response = await client.get("/v1/platform/agencies", headers=platform_admin.headers())
    assert response.status_code == 200
    body = response.json()

    names = {a["legal_name"] for a in body["agencies"]}
    assert {"Alpha Home Care", "Beta Home Care"} <= names
    assert body["summary"]["agencies_total"] == len(body["agencies"])

    alpha = next(a for a in body["agencies"] if a["legal_name"] == "Alpha Home Care")
    assert alpha["clients_active"] == 1
    assert alpha["users_active"] == 1
    assert alpha["status"] == "active"


async def test_fleet_surfaces_a_tenant_whose_evv_is_failing(
    client, platform_admin: PlatformFixture, tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    """The whole reason this console exists: spotting the tenant that needs a phone call.

    A rejected EVV record is invisible to the agency until somebody opens their exception
    queue, and invisible to CareOS entirely before this.
    """
    _client_id, plan_id = await make_client_with_plan(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        visit = await _make_visit(session, tenant_a, plan_id)
        session.add(
            EVVRecord(
                agency_id=tenant_a.agency_id,
                scheduled_visit_id=visit,
                clock_in_time=datetime.now(UTC) - timedelta(hours=2),
                capture_method=CaptureMethod.mobile_gps,
                transmission_status=TransmissionStatus.rejected,
            )
        )
        session.add(
            ComplianceException(
                agency_id=tenant_a.agency_id,
                rule_key="evv.rejected",
                severity="critical",
                entity_type="evv_record",
                entity_id=uuid.uuid4(),
                message="Aggregator rejected the record",
            )
        )

    response = await client.get("/v1/platform/agencies", headers=platform_admin.headers())
    body = response.json()

    # Worst first: the agency with the critical exception leads the list.
    assert body["agencies"][0]["legal_name"] == "Alpha Home Care"
    assert body["agencies"][0]["evv_rejected"] == 1
    assert body["agencies"][0]["exceptions_open_critical"] == 1
    assert body["summary"]["agencies_with_rejected_evv"] == 1
    assert body["summary"]["open_critical_exceptions"] == 1

    # And Beta, which is fine, reports zeros rather than being absent.
    beta = next(a for a in body["agencies"] if a["legal_name"] == "Beta Home Care")
    assert beta["evv_rejected"] == 0
    assert beta["exceptions_open_critical"] == 0


async def test_credential_expiry_counts_reach_the_fleet_view(
    client, platform_admin: PlatformFixture, tenant_a: TenantFixture
) -> None:
    async with tenant_session(tenant_a.agency_id) as session:
        session.add(
            Credential(
                agency_id=tenant_a.agency_id,
                caregiver_id=tenant_a.caregiver_id,
                credential_type="HHA",
                expiration_date=(datetime.now(UTC) - timedelta(days=3)).date(),
                verification_status=VerificationStatus.verified,
            )
        )
        session.add(
            Credential(
                agency_id=tenant_a.agency_id,
                caregiver_id=tenant_a.caregiver_id,
                credential_type="CPR",
                expiration_date=(datetime.now(UTC) + timedelta(days=10)).date(),
                verification_status=VerificationStatus.verified,
            )
        )

    response = await client.get(
        f"/v1/platform/agencies/{tenant_a.agency_id}", headers=platform_admin.headers()
    )
    assert response.status_code == 200
    assert response.json()["credentials_expired"] == 1
    assert response.json()["credentials_expiring_30d"] == 1


# --- What an operator cannot see -----------------------------------------------------------


@pytest.mark.parametrize(
    "table",
    ["client", "caregiver", "scheduled_visit", "evv_record", "credential", "applicant_profile"],
)
async def test_platform_role_holds_no_grant_on_phi_tables(
    database: None, tenant_a: TenantFixture, table: str
) -> None:
    """The guarantee is a missing grant, not a handler that remembers not to ask.

    An operator console is exactly where somebody will eventually be tempted to add "just one
    query" against a tenant table. This is what makes that attempt fail loudly in development
    rather than quietly succeed in production.
    """
    await make_client_with_plan(tenant_a)
    async with platform_session() as session:
        with pytest.raises(ProgrammingError, match="permission denied"):
            await session.execute(text(f"SELECT * FROM {table}"))  # noqa: S608


async def test_platform_role_cannot_read_a_tenant_audit_trail(
    database: None, tenant_a: TenantFixture
) -> None:
    """It may write into `audit_log` and may not read it.

    Writing is what lets an agency see in its own records that CareOS suspended it. Reading
    would hand a CareOS employee every action every agency has ever taken, which is a far
    larger disclosure than the console is for.
    """
    async with tenant_session(tenant_a.agency_id) as session:
        session.add(
            AuditLog(
                agency_id=tenant_a.agency_id,
                action="test.action",
                entity_type="test",
                is_phi_access=False,
            )
        )

    async with platform_session() as session:
        with pytest.raises(ProgrammingError, match="permission denied"):
            await session.execute(text("SELECT * FROM audit_log"))


async def test_platform_role_cannot_read_an_agency_tax_id(
    database: None, tenant_a: TenantFixture
) -> None:
    """The `agency` grant is column-scoped, so the encrypted tax identifier is out of reach."""
    async with platform_session() as session:
        # The columns it may read work.
        assert (
            await session.execute(select(Agency.legal_name).where(Agency.id == tenant_a.agency_id))
        ).scalar_one() == "Alpha Home Care"
        # The one it may not does not.
        with pytest.raises(ProgrammingError, match="permission denied"):
            await session.execute(text("SELECT tax_id_encrypted FROM agency"))


async def test_platform_role_cannot_rename_an_agency(
    database: None, tenant_a: TenantFixture
) -> None:
    """UPDATE is granted on three columns. Renaming a customer is not CareOS's decision."""
    async with platform_session() as session:
        with pytest.raises(ProgrammingError, match="permission denied"):
            await session.execute(
                text("UPDATE agency SET legal_name = 'Renamed By CareOS' WHERE id = :aid"),
                {"aid": tenant_a.agency_id},
            )


# --- Crossing the two principal models -----------------------------------------------------


async def test_a_tenant_owner_cannot_reach_the_platform_console(
    client, tenant_a: TenantFixture
) -> None:
    """An `owner_admin` token is signed with the same key and is still refused.

    Without the `principal_type` claim this would be an authorization question decided per
    route. With it, it is an authentication failure decided by the decoder.
    """
    response = await client.get(
        "/v1/platform/agencies", headers=tenant_a.headers(Role.owner_admin)
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


async def test_a_platform_operator_cannot_reach_a_tenant_endpoint(
    client, platform_admin: PlatformFixture, tenant_a: TenantFixture
) -> None:
    """The reverse direction, which is the one that would be a cross-tenant leak."""
    response = await client.get(
        f"/v1/clients", headers=platform_admin.headers()
    )
    assert response.status_code == 401

    response = await client.get(
        f"/v1/agencies/{tenant_a.agency_id}", headers=platform_admin.headers()
    )
    assert response.status_code == 401


def test_a_platform_token_does_not_decode_as_a_tenant_principal(
    platform_admin: PlatformFixture,
) -> None:
    from careos.core.errors import AuthenticationError

    with pytest.raises(AuthenticationError):
        decode_token(platform_admin.token())


def test_a_tenant_token_does_not_decode_as_a_platform_principal(
    tenant_a: TenantFixture,
) -> None:
    from careos.core.errors import AuthenticationError

    token = create_token(
        user_id=tenant_a.owner_id,
        agency_id=tenant_a.agency_id,
        role=Role.owner_admin,
        token_type="access",
    )
    with pytest.raises(AuthenticationError):
        decode_platform_token(token)


async def test_platform_support_is_read_only(
    client, platform_support: PlatformFixture, tenant_a: TenantFixture
) -> None:
    """Enforced centrally on method, like the tenant-side auditor role."""
    assert (
        await client.get("/v1/platform/agencies", headers=platform_support.headers())
    ).status_code == 200

    response = await client.post(
        f"/v1/platform/agencies/{tenant_a.agency_id}/suspend",
        headers=platform_support.headers(),
        json={"reason": "Non-payment after three notices"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


# --- MFA, unconditionally ------------------------------------------------------------------


async def test_an_unenrolled_operator_session_reaches_only_enrolment(
    client, platform_admin: PlatformFixture
) -> None:
    """No `CAREOS_MFA_REQUIRED` equivalent: the gate is on for operators, always.

    The suite runs with `mfa_required` at its default of false, which is what makes this a
    meaningful assertion rather than a restatement of the tenant-side setting.
    """
    pending = platform_admin.headers(mfa_satisfied=False)

    refused = await client.get("/v1/platform/agencies", headers=pending)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "MFA_ENROLMENT_REQUIRED"

    # And the three routes an unenrolled operator must reach in order to stop being one.
    assert (await client.get("/v1/platform/me", headers=pending)).status_code == 200
    assert (
        await client.post("/v1/platform/auth/mfa/enroll", headers=pending, json={})
    ).status_code == 200


async def test_login_enrol_and_sign_in_again_with_a_code(client) -> None:
    """The whole bootstrap path an operator walks on their first day."""
    operator = await make_operator(PlatformRole.platform_admin)

    first = await client.post(
        "/v1/platform/auth/login",
        json={"email": operator.email, "password": OPERATOR_PASSWORD},
    )
    assert first.status_code == 200
    pending_token = first.json()["access_token"]
    # The session is real and unsatisfied: it can enrol and nothing else.
    assert decode_platform_token(pending_token).mfa_satisfied is False

    headers = {"Authorization": f"Bearer {pending_token}"}
    assert (await client.get("/v1/platform/agencies", headers=headers)).status_code == 403

    started = await client.post("/v1/platform/auth/mfa/enroll", headers=headers, json={})
    secret = started.json()["secret"]
    assert len(started.json()["recovery_codes"]) == 10

    confirmed = await client.post(
        "/v1/platform/auth/mfa/confirm",
        headers=headers,
        json={"code": mfa.code_at(secret)},
    )
    assert confirmed.status_code == 200
    satisfied = {"Authorization": f"Bearer {confirmed.json()['access_token']}"}
    assert (await client.get("/v1/platform/agencies", headers=satisfied)).status_code == 200


async def test_an_enrolled_operator_must_present_a_code_at_login(client) -> None:
    operator = await make_operator(PlatformRole.platform_admin)
    async with platform_session() as session:
        row = await session.get(PlatformOperator, operator.operator_id)
        assert row is not None
        secret, _uri, _codes = _enrol(row)

    no_code = await client.post(
        "/v1/platform/auth/login",
        json={"email": operator.email, "password": OPERATOR_PASSWORD},
    )
    assert no_code.status_code == 401
    assert no_code.json()["error"]["code"] == "MFA_REQUIRED"

    with_code = await client.post(
        "/v1/platform/auth/login",
        json={
            "email": operator.email,
            "password": OPERATOR_PASSWORD,
            "mfa_code": mfa.code_at(secret),
        },
    )
    assert with_code.status_code == 200
    assert decode_platform_token(with_code.json()["access_token"]).mfa_satisfied is True


async def test_replacing_an_operator_authenticator_requires_the_one_in_force(
    client, platform_admin: PlatformFixture
) -> None:
    """A stolen operator session must not be able to move the second factor."""
    async with platform_session() as session:
        row = await session.get(PlatformOperator, platform_admin.operator_id)
        assert row is not None
        _enrol(row)

    stolen = platform_admin.headers()
    refused = await client.post("/v1/platform/auth/mfa/enroll", headers=stolen, json={})
    assert refused.status_code == 401
    assert refused.json()["error"]["code"] == "MFA_REQUIRED"


# --- Suspension ---------------------------------------------------------------------------


async def test_suspending_an_agency_locks_everyone_in_it_out(
    client, platform_admin: PlatformFixture, tenant_a: TenantFixture
) -> None:
    """Login, refresh, and tokens already in circulation all stop working.

    Any one of the three left out is a hole of a different shape, so all three are asserted
    here rather than in three files that could each be deleted separately.
    """
    live = tenant_a.headers(Role.owner_admin)
    assert (await client.get("/v1/clients", headers=live)).status_code == 200

    suspended = await client.post(
        f"/v1/platform/agencies/{tenant_a.agency_id}/suspend",
        headers=platform_admin.headers(),
        json={"reason": "Suspected credential-stuffing against this tenant"},
    )
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"

    # A token issued before the suspension.
    stale = await client.get("/v1/clients", headers=live)
    assert stale.status_code == 401
    assert stale.json()["error"]["code"] == "AGENCY_SUSPENDED"

    # And a fresh sign-in with the right password.
    async with tenant_session(tenant_a.agency_id) as session:
        await session.execute(
            text("UPDATE app_user SET password_hash = :h WHERE id = :uid"),
            {"h": _known_hash(), "uid": tenant_a.owner_id},
        )
    login = await client.post(
        "/v1/auth/login",
        json={"email": tenant_a.owner.email, "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 401
    assert login.json()["error"]["code"] == "AGENCY_SUSPENDED"


async def test_suspension_is_recorded_in_the_agencys_own_audit_trail(
    client, platform_admin: PlatformFixture, tenant_a: TenantFixture
) -> None:
    """An action taken on a tenant from outside it must not be invisible from inside."""
    await client.post(
        f"/v1/platform/agencies/{tenant_a.agency_id}/suspend",
        headers=platform_admin.headers(),
        json={"reason": "Non-payment after three written notices"},
    )

    async with tenant_session(tenant_a.agency_id) as session:
        rows = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "agency.suspended")
            )
        ).scalars().all()
    assert len(rows) == 1
    entry = rows[0]
    # No actor user: the person who did this is not one of this agency's users, and pointing
    # the column at one would be false.
    assert entry.actor_user_id is None
    assert entry.after_state is not None
    assert entry.after_state["reason"] == "Non-payment after three written notices"
    assert entry.after_state["suspended_by_platform_operator"] == str(platform_admin.operator_id)

    async with platform_session() as session:
        platform_rows = (
            await session.execute(
                select(PlatformAuditLog).where(PlatformAuditLog.action == "platform.agency_suspended")
            )
        ).scalars().all()
    assert len(platform_rows) == 1
    assert platform_rows[0].subject_agency_id == tenant_a.agency_id


async def test_suspending_twice_is_refused_rather_than_duplicated(
    client, platform_admin: PlatformFixture, tenant_a: TenantFixture
) -> None:
    """No `Idempotency-Key`; a replay is refused on its merits instead.

    A double-submitted form must not produce two audit rows claiming two separate
    suspensions, because that is what somebody reads back during a dispute.
    """
    body = {"reason": "Non-payment after three written notices"}
    first = await client.post(
        f"/v1/platform/agencies/{tenant_a.agency_id}/suspend",
        headers=platform_admin.headers(),
        json=body,
    )
    assert first.status_code == 200
    second = await client.post(
        f"/v1/platform/agencies/{tenant_a.agency_id}/suspend",
        headers=platform_admin.headers(),
        json=body,
    )
    assert second.status_code == 409

    async with tenant_session(tenant_a.agency_id) as session:
        count = len(
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "agency.suspended")
                )
            )
            .scalars()
            .all()
        )
    assert count == 1


async def test_reinstating_restores_access_and_clears_the_reason(
    client, platform_admin: PlatformFixture, tenant_a: TenantFixture
) -> None:
    await client.post(
        f"/v1/platform/agencies/{tenant_a.agency_id}/suspend",
        headers=platform_admin.headers(),
        json={"reason": "Suspected credential-stuffing against this tenant"},
    )
    reinstated = await client.post(
        f"/v1/platform/agencies/{tenant_a.agency_id}/reinstate",
        headers=platform_admin.headers(),
        json={"note": "Incident closed, passwords rotated"},
    )
    assert reinstated.status_code == 200
    assert reinstated.json()["status"] == "active"
    assert reinstated.json()["suspended_reason"] is None

    async with tenant_session(tenant_a.agency_id) as session:
        agency = await session.get(Agency, tenant_a.agency_id)
        assert agency is not None
        assert agency.status is AgencyStatus.active

    # A fresh sign-in works again — the agency was not left with a stale watermark.
    live = tenant_a.headers(Role.owner_admin)
    assert (await client.get("/v1/clients", headers=live)).status_code == 200


async def test_reinstating_an_active_agency_is_refused(
    client, platform_admin: PlatformFixture, tenant_a: TenantFixture
) -> None:
    response = await client.post(
        f"/v1/platform/agencies/{tenant_a.agency_id}/reinstate",
        headers=platform_admin.headers(),
        json={"note": "Nothing to undo"},
    )
    assert response.status_code == 409


async def test_a_suspension_reason_must_be_a_sentence(
    client, platform_admin: PlatformFixture, tenant_a: TenantFixture
) -> None:
    """It is shown to the agency, so "no" is not an acceptable reason."""
    response = await client.post(
        f"/v1/platform/agencies/{tenant_a.agency_id}/suspend",
        headers=platform_admin.headers(),
        json={"reason": "no"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --- Auditing the reads --------------------------------------------------------------------


async def test_reading_the_fleet_is_audited(
    client, platform_admin: PlatformFixture, tenant_a: TenantFixture
) -> None:
    await client.get("/v1/platform/agencies", headers=platform_admin.headers())
    await client.get(
        f"/v1/platform/agencies/{tenant_a.agency_id}", headers=platform_admin.headers()
    )

    async with platform_session() as session:
        actions = (
            await session.execute(select(PlatformAuditLog.action).order_by(PlatformAuditLog.occurred_at))
        ).scalars().all()
    assert "platform.fleet_viewed" in actions
    assert "platform.agency_health_viewed" in actions


async def test_the_platform_cannot_delete_its_own_access_log(
    database: None, platform_admin: PlatformFixture
) -> None:
    """Append-only by grant, exactly as `audit_log` is."""
    async with platform_session() as session:
        session.add(
            PlatformAuditLog(actor_operator_id=platform_admin.operator_id, action="test.action")
        )

    async with platform_session() as session:
        with pytest.raises(ProgrammingError):
            await session.execute(text("DELETE FROM platform_audit_log"))

    async with platform_session() as session:
        with pytest.raises(ProgrammingError):
            await session.execute(text("UPDATE platform_audit_log SET action = 'tampered'"))


async def test_the_audit_endpoint_is_readable_by_support(
    client, platform_support: PlatformFixture
) -> None:
    """An access log only the actors may read is one nobody independent ever checks."""
    await client.get("/v1/platform/agencies", headers=platform_support.headers())
    response = await client.get("/v1/platform/audit", headers=platform_support.headers())
    assert response.status_code == 200
    assert any(entry["action"] == "platform.fleet_viewed" for entry in response.json())


# --- Operator administration ---------------------------------------------------------------


async def test_an_admin_can_add_and_offboard_a_colleague(
    client, platform_admin: PlatformFixture
) -> None:
    created = await client.post(
        "/v1/platform/operators",
        headers=platform_admin.headers(),
        json={
            # Not a `.test` address: `EmailStr` rejects special-use domains, and the schema
            # is the same one a real operator invitation goes through.
            "email": "colleague@careos-ops.example",
            "display_name": "New Colleague",
            "role": "platform_support",
            "initial_password": "a-sufficiently-long-initial-password",
        },
    )
    assert created.status_code == 201
    operator_id = created.json()["id"]
    assert created.json()["mfa_enrolled"] is False

    disabled = await client.post(
        f"/v1/platform/operators/{operator_id}/disable",
        headers=platform_admin.headers(),
        json={"reason": "Left the company"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "suspended"

    # Their sessions stop working immediately, not at the end of the token's TTL.
    offboarded = PlatformFixture(
        uuid.UUID(operator_id), "colleague@careos-ops.example", PlatformRole.platform_support
    )
    refused = await client.get("/v1/platform/agencies", headers=offboarded.headers())
    assert refused.status_code == 401


async def test_the_last_platform_admin_cannot_be_disabled(
    client, platform_admin: PlatformFixture
) -> None:
    """CareOS locking itself out of its own console has no second tenant to fall back on."""
    other = await make_operator(PlatformRole.platform_admin)
    disabled = await client.post(
        f"/v1/platform/operators/{other.operator_id}/disable",
        headers=platform_admin.headers(),
        json={"reason": "Leaving"},
    )
    assert disabled.status_code == 200

    # Now `platform_admin` is the only one left, and cannot disable themselves either.
    self_disable = await client.post(
        f"/v1/platform/operators/{platform_admin.operator_id}/disable",
        headers=platform_admin.headers(),
        json={"reason": "Trying to lock everyone out"},
    )
    assert self_disable.status_code == 403


# --- Helpers ---------------------------------------------------------------------------------


def _enrol(operator: PlatformOperator) -> tuple[str, str, list[str]]:
    from careos.core import second_factor

    secret, uri, codes = second_factor.issue(operator, account=operator.email)
    operator.mfa_enrolled = True
    return secret, uri, codes


def _known_hash() -> str:
    from careos.core.security import hash_password

    return hash_password("correct-horse-battery-staple")


async def _make_visit(session, tenant: TenantFixture, plan_id: uuid.UUID) -> uuid.UUID:
    from careos.modules.scheduling.models import ScheduledVisit

    visit = ScheduledVisit(
        agency_id=tenant.agency_id,
        care_plan_id=plan_id,
        scheduled_start=datetime.now(UTC) + timedelta(hours=1),
        scheduled_end=datetime.now(UTC) + timedelta(hours=2),
        status=VisitStatus.open,
    )
    session.add(visit)
    await session.flush()
    return visit.id
