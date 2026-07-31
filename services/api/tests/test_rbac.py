"""RBAC and authentication tests (`08_Security_Architecture.md` Section 1)."""

from __future__ import annotations

import uuid

import pytest
from fastapi import APIRouter, FastAPI

from careos.core.errors import AuthenticationError
from careos.core.rbac import (
    assert_all_routes_declare_access,
    assert_route_discovery_is_working,
    route_access_map,
)
from careos.core.security import create_token, decode_token
from careos.modules.agency.models import Role
from tests.conftest import TenantFixture

#: Routes that must exist with exactly these permitted roles. Hard-coded rather than
#: derived, so that a change to any route's access rules has to be made deliberately here
#: as well as in the router — and so a broken route-discovery traversal cannot make this
#: file pass by finding nothing.
EXPECTED_ACCESS: dict[str, list[str]] = {
    "GET /health": ["*public*"],
    # Public in the RBAC sense only: a scraper has no agency and fits no role in this model,
    # so inventing one would put a login in the monitoring path. It is gated by a bearer token
    # from configuration instead, which production cannot boot without.
    "GET /metrics": ["*public*"],
    "GET /v1/agencies/{agency_id}": [
        "auditor",
        "billing_rcm",
        "clinical_supervisor",
        "owner_admin",
        "scheduler",
    ],
    "GET /v1/agencies/{agency_id}/compliance-reviews": ["auditor", "owner_admin"],
    "GET /v1/agencies/{agency_id}/users": ["auditor", "owner_admin"],
    "GET /v1/care-plans/{care_plan_id}": [
        "auditor",
        "clinical_supervisor",
        "owner_admin",
        "scheduler",
    ],
    "GET /v1/caregivers": ["auditor", "clinical_supervisor", "owner_admin", "scheduler"],
    "GET /v1/caregivers/{caregiver_id}": [
        "auditor",
        "clinical_supervisor",
        "owner_admin",
        "scheduler",
    ],
    "GET /v1/caregivers/{caregiver_id}/credentials": [
        "auditor",
        "clinical_supervisor",
        "owner_admin",
        "scheduler",
    ],
    "GET /v1/clients": ["auditor", "clinical_supervisor", "owner_admin", "scheduler"],
    "GET /v1/clients/{client_id}": ["auditor", "clinical_supervisor", "owner_admin", "scheduler"],
    "GET /v1/clients/{client_id}/care-plans": [
        "auditor",
        "clinical_supervisor",
        "owner_admin",
        "scheduler",
    ],
    "GET /v1/compliance-exceptions": ["auditor", "clinical_supervisor", "owner_admin", "scheduler"],
    "GET /v1/compliance-exceptions/summary": [
        "auditor",
        "clinical_supervisor",
        "owner_admin",
        "scheduler",
    ],
    "GET /v1/job-postings": ["auditor", "owner_admin", "scheduler"],
    "GET /v1/my-visits": ["caregiver"],
    "GET /v1/job-postings/{job_posting_id}/applicants": ["auditor", "owner_admin", "scheduler"],
    "GET /v1/reports/credential-expirations": [
        "auditor",
        "clinical_supervisor",
        "owner_admin",
        "scheduler",
    ],
    "GET /v1/reports/recruiting-funnel": ["auditor", "owner_admin", "scheduler"],
    "GET /v1/visits": ["auditor", "caregiver", "clinical_supervisor", "owner_admin", "scheduler"],
    "GET /v1/visits/gaps": ["owner_admin", "scheduler"],
    "GET /v1/visits/{visit_id}": [
        "auditor",
        "caregiver",
        "clinical_supervisor",
        "owner_admin",
        "scheduler",
    ],
    "GET /v1/visits/{visit_id}/compliance": [
        "auditor",
        "clinical_supervisor",
        "owner_admin",
        "scheduler",
    ],
    "GET /v1/visits/{visit_id}/evv-status": ["auditor", "caregiver", "owner_admin", "scheduler"],
    "GET /v1/visits/{visit_id}/suggested-caregivers": ["owner_admin", "scheduler"],
    "PATCH /v1/agencies/{agency_id}": ["owner_admin"],
    "PATCH /v1/users/{user_id}/role": ["owner_admin"],
    "POST /v1/agencies": ["*public*"],
    # A full-agency PHI extract in one file. Owner-admin only, and deliberately not the
    # auditor: tenant-wide read access is not a licence to walk out with the whole data set.
    "POST /v1/agencies/{agency_id}/export": ["owner_admin"],
    "POST /v1/agencies/{agency_id}/users": ["owner_admin"],
    "POST /v1/applicants": ["owner_admin", "scheduler"],
    "POST /v1/applicants/{applicant_id}/hire": ["owner_admin"],
    "POST /v1/applicants/{applicant_id}/stage": ["owner_admin", "scheduler"],
    "POST /v1/auth/login": ["*public*"],
    "POST /v1/auth/refresh": ["*public*"],
    "POST /v1/care-plans/{care_plan_id}/generate-visits": ["owner_admin", "scheduler"],
    "POST /v1/caregivers": ["owner_admin", "scheduler"],
    "POST /v1/caregivers/{caregiver_id}/credentials": ["owner_admin", "scheduler"],
    "POST /v1/caregivers/{caregiver_id}/exclusion-check": ["owner_admin"],
    "POST /v1/caregivers/{caregiver_id}/terminate": ["owner_admin"],
    "POST /v1/clients": ["clinical_supervisor", "owner_admin", "scheduler"],
    "POST /v1/clients/{client_id}/care-plans": ["clinical_supervisor", "owner_admin"],
    "POST /v1/compliance-exceptions/{exception_id}/resolve": [
        "clinical_supervisor",
        "owner_admin",
        "scheduler",
    ],
    "POST /v1/job-postings": ["owner_admin", "scheduler"],
    "POST /v1/users/{user_id}/revoke-sessions": ["owner_admin"],
    "POST /v1/visits/{visit_id}/assign": ["owner_admin", "scheduler"],
    "POST /v1/visits/{visit_id}/clock-in": ["caregiver", "owner_admin", "scheduler"],
    "POST /v1/visits/{visit_id}/clock-out": ["caregiver", "owner_admin", "scheduler"],
}


def test_every_route_declares_access(app: FastAPI) -> None:
    assert_all_routes_declare_access(app)


def test_route_access_matches_the_expected_matrix(app: FastAPI) -> None:
    assert route_access_map(app) == EXPECTED_ACCESS


def test_route_discovery_finds_all_routes(app: FastAPI) -> None:
    """Guards against a FastAPI change that makes the access check inspect nothing."""
    assert_route_discovery_is_working(app, minimum=len(EXPECTED_ACCESS))


def test_startup_check_rejects_a_route_with_no_declaration() -> None:
    """The gate must actually fail on an undeclared route, not just pass on good ones."""
    rogue = FastAPI()
    router = APIRouter()

    @router.get("/forgot-to-declare")
    async def _handler() -> dict[str, str]:
        return {}

    rogue.include_router(router)

    with pytest.raises(RuntimeError, match="missing an access declaration"):
        assert_all_routes_declare_access(rogue)


async def test_unauthenticated_request_is_rejected(client) -> None:
    response = await client.get(f"/v1/agencies/{uuid.uuid4()}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


async def test_wrong_role_is_rejected(client, tenant_a: TenantFixture) -> None:
    """A scheduler may not change user roles — that is owner_admin only."""
    response = await client.patch(
        f"/v1/users/{tenant_a.owner_id}/role",
        headers=tenant_a.headers(Role.scheduler),
        json={"role": "auditor"},
    )
    assert response.status_code == 403
    body = response.json()["error"]
    assert body["code"] == "PERMISSION_DENIED"
    assert body["details"]["required_roles"] == ["owner_admin"]


async def test_auditor_cannot_mutate(client, tenant_a: TenantFixture) -> None:
    """The auditor role is read-only tenant-wide, enforced centrally on method."""
    response = await client.post(
        "/v1/clients",
        headers=tenant_a.headers(Role.auditor),
        json={
            "legal_name": "Should Not Be Created",
            "service_state": "NY",
            "primary_payer_type": "private_pay",
        },
    )
    assert response.status_code == 403


async def test_auditor_can_read(client, tenant_a: TenantFixture) -> None:
    response = await client.get("/v1/clients", headers=tenant_a.headers(Role.auditor))
    assert response.status_code == 200


async def test_refresh_token_is_not_accepted_as_an_access_token(
    client, tenant_a: TenantFixture
) -> None:
    """Otherwise a long-lived refresh token would silently defeat the short access TTL."""
    refresh = create_token(
        user_id=tenant_a.owner_id,
        agency_id=tenant_a.agency_id,
        role=Role.owner_admin,
        token_type="refresh",
    )
    response = await client.get(
        f"/v1/agencies/{tenant_a.agency_id}", headers={"Authorization": f"Bearer {refresh}"}
    )
    assert response.status_code == 401


def test_access_token_is_not_accepted_as_a_refresh_token(tenant_a: TenantFixture) -> None:
    access = create_token(
        user_id=tenant_a.owner_id,
        agency_id=tenant_a.agency_id,
        role=Role.owner_admin,
        token_type="access",
    )
    with pytest.raises(AuthenticationError):
        decode_token(access, expected_type="refresh")


async def test_malformed_authorization_header_is_rejected(client) -> None:
    response = await client.get(
        f"/v1/agencies/{uuid.uuid4()}", headers={"Authorization": "Basic abc123"}
    )
    assert response.status_code == 401


async def test_owner_cannot_demote_themselves(client, tenant_a: TenantFixture) -> None:
    """Prevents a tenant locking itself out of administration."""
    response = await client.patch(
        f"/v1/users/{tenant_a.owner_id}/role",
        headers=tenant_a.headers(Role.owner_admin),
        json={"role": "scheduler"},
    )
    assert response.status_code == 403
