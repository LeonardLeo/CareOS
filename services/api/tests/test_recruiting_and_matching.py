"""Recruiting pipeline, shift matching, and credentialing dashboard tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from careos.core.errors import ConflictError
from careos.db.session import tenant_session
from careos.modules.agency.models import Role
from careos.modules.audit import compliance_log
from careos.modules.audit.compliance_log_models import ReviewOutcome, ReviewType
from careos.modules.credentialing import service as credentialing
from careos.modules.credentialing.models import (
    Caregiver,
    EmploymentStatus,
    ExclusionCheckStatus,
    VerificationStatus,
)
from careos.modules.recruiting import service as recruiting
from careos.modules.recruiting.models import PipelineStage
from careos.modules.scheduling import matching
from careos.modules.scheduling import service as scheduling
from careos.modules.scheduling.models import CarePlan, ScheduledVisit
from tests.conftest import TenantFixture, make_client_with_plan

# --- Recruiting pipeline -------------------------------------------------------------------


async def test_applicant_pipeline_end_to_end(client, tenant_a: TenantFixture) -> None:
    headers = tenant_a.headers(Role.owner_admin)

    posting = await client.post(
        "/v1/job-postings",
        headers=headers,
        json={
            "title": "Home Health Aide — Brooklyn",
            "required_credential_types": ["HHA", "CPR"],
            "service_state": "ny",
        },
    )
    assert posting.status_code == 201, posting.text
    assert posting.json()["service_state"] == "NY"
    posting_id = posting.json()["id"]

    applicant = await client.post(
        "/v1/applicants",
        headers=headers,
        json={
            "job_posting_id": posting_id,
            "source": "indeed",
            "full_name": "Grace Applicant",
            "email": "grace@example.com",
            "claimed_credentials": ["HHA", "CPR"],
            "availability": {"days": ["mon", "tue", "wed", "thu", "fri"]},
            "geo_lat": 40.7128,
            "geo_lng": -74.0060,
        },
    )
    assert applicant.status_code == 201, applicant.text
    applicant_id = applicant.json()["id"]
    assert applicant.json()["pipeline_stage"] == "applied"

    # Scores are computed but withheld until the agency leaves its ranking shadow period
    # (`13_Phase_1_Launch_Plan.md` 6.3), so this walks the real route out of it: record the
    # bias audit, then enable display. Asserting on scores without this would be asserting on
    # a state no agency reaches by default.
    withheld = await client.get(f"/v1/job-postings/{posting_id}/applicants", headers=headers)
    assert withheld.json()[0]["ranking_displayed"] is False
    assert withheld.json()[0]["ranking_score"] is None

    async with tenant_session(tenant_a.agency_id) as session:
        await compliance_log.record_review(
            session,
            principal=tenant_a.principal(),
            agency_id=tenant_a.agency_id,
            review_type=ReviewType.ai_hiring_bias_audit,
            outcome=ReviewOutcome.passed,
            performed_by="Employment counsel",
        )
    enabled = await client.post(
        f"/v1/agencies/{tenant_a.agency_id}/ranking-display", headers=headers
    )
    assert enabled.status_code == 200, enabled.text

    ranked = await client.get(f"/v1/job-postings/{posting_id}/applicants", headers=headers)
    assert ranked.status_code == 200
    scored = ranked.json()[0]
    assert scored["ranking_score"] is not None
    assert scored["ranking_factors"], "a score must never ship without its factors"
    assert scored["ranking_model_version"]

    for stage in ("screened", "offer"):
        response = await client.post(
            f"/v1/applicants/{applicant_id}/stage", headers=headers, json={"stage": stage}
        )
        assert response.status_code == 200, response.text

    hired = await client.post(f"/v1/applicants/{applicant_id}/hire", headers=headers)
    assert hired.status_code == 201, hired.text
    caregiver = hired.json()
    assert caregiver["employment_status"] == "onboarding"
    # Hiring does not imply clearance to work a Medicaid visit (US-1.3.2).
    assert caregiver["exclusion_check_status"] == "not_run"


async def test_invalid_stage_transition_is_refused(tenant_a: TenantFixture) -> None:
    """A rejected applicant is not silently revived, and hired is terminal."""
    async with tenant_session(tenant_a.agency_id) as session:
        applicant = await recruiting.ingest_applicant(
            session,
            principal=tenant_a.principal(),
            job_posting_id=None,
            source="direct",
            full_name="Test Applicant",
            email=None,
            phone=None,
            claimed_credentials=[],
            availability={},
            geo_lat=None,
            geo_lng=None,
        )
        # applied -> offer skips screening
        with pytest.raises(ConflictError, match="Cannot move"):
            await recruiting.advance_stage(
                session,
                principal=tenant_a.principal(),
                applicant=applicant,
                to_stage=PipelineStage.offer,
            )

        await recruiting.advance_stage(
            session,
            principal=tenant_a.principal(),
            applicant=applicant,
            to_stage=PipelineStage.rejected,
        )
        with pytest.raises(ConflictError):
            await recruiting.advance_stage(
                session,
                principal=tenant_a.principal(),
                applicant=applicant,
                to_stage=PipelineStage.screened,
            )


async def test_hiring_twice_returns_the_same_caregiver(tenant_a: TenantFixture) -> None:
    """Guards against a double-submit creating two caregiver records for one person."""
    async with tenant_session(tenant_a.agency_id) as session:
        applicant = await recruiting.ingest_applicant(
            session,
            principal=tenant_a.principal(),
            job_posting_id=None,
            source="direct",
            full_name="Duplicate Hire",
            email=None,
            phone=None,
            claimed_credentials=[],
            availability={},
            geo_lat=None,
            geo_lng=None,
        )
        for stage in (PipelineStage.screened, PipelineStage.offer):
            await recruiting.advance_stage(
                session, principal=tenant_a.principal(), applicant=applicant, to_stage=stage
            )
        first = await recruiting.hire_applicant(
            session, principal=tenant_a.principal(), applicant=applicant
        )
        second = await recruiting.hire_applicant(
            session, principal=tenant_a.principal(), applicant=applicant
        )
    assert first.id == second.id


async def test_ranking_never_writes_a_score_without_factors(tenant_a: TenantFixture) -> None:
    """The database constraint backs up the application invariant.

    US-1.2.2's explainability requirement is only meaningful if it cannot be bypassed by a
    code path that writes a bare number.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    async with tenant_session(tenant_a.agency_id) as session:
        applicant = await recruiting.ingest_applicant(
            session,
            principal=tenant_a.principal(),
            job_posting_id=None,
            source="direct",
            full_name="No Factors",
            email=None,
            phone=None,
            claimed_credentials=[],
            availability={},
            geo_lat=None,
            geo_lng=None,
        )
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "UPDATE applicant_profile SET ranking_score = 0.9, "
                    "ranking_factors = '[]'::jsonb WHERE id = :aid"
                ),
                {"aid": applicant.id},
            )


async def test_recruiting_funnel_counts_cumulatively(client, tenant_a: TenantFixture) -> None:
    """Someone hired also counts as having been screened, or conversion is meaningless."""
    headers = tenant_a.headers()
    async with tenant_session(tenant_a.agency_id) as session:
        for index in range(4):
            applicant = await recruiting.ingest_applicant(
                session,
                principal=tenant_a.principal(),
                job_posting_id=None,
                source="direct",
                full_name=f"Applicant {index}",
                email=None,
                phone=None,
                claimed_credentials=[],
                availability={},
                geo_lat=None,
                geo_lng=None,
            )
            if index < 2:
                await recruiting.advance_stage(
                    session,
                    principal=tenant_a.principal(),
                    applicant=applicant,
                    to_stage=PipelineStage.screened,
                )
            elif index == 2:
                await recruiting.advance_stage(
                    session,
                    principal=tenant_a.principal(),
                    applicant=applicant,
                    to_stage=PipelineStage.rejected,
                )

    response = await client.get("/v1/reports/recruiting-funnel", headers=headers)
    assert response.status_code == 200
    stages = {s["stage"]: s for s in response.json()}

    # 4 applied (including the rejected one), 2 reached screened.
    assert stages["applied"]["count"] == 4
    assert stages["screened"]["count"] == 2
    assert stages["screened"]["conversion_from_previous"] == 0.5
    assert stages["applied"]["conversion_from_previous"] is None


async def test_applicants_are_tenant_scoped(
    client, tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    async with tenant_session(tenant_a.agency_id) as session:
        await recruiting.ingest_applicant(
            session,
            principal=tenant_a.principal(),
            job_posting_id=None,
            source="direct",
            full_name="Tenant A Applicant",
            email=None,
            phone=None,
            claimed_credentials=[],
            availability={},
            geo_lat=None,
            geo_lng=None,
        )

    response = await client.get("/v1/reports/recruiting-funnel", headers=tenant_b.headers())
    assert response.status_code == 200
    assert all(stage["count"] == 0 for stage in response.json())


# --- Shift matching ------------------------------------------------------------------------


async def _visit_for_matching(tenant: TenantFixture) -> ScheduledVisit:
    """Generate a visit that is reliably in the future.

    The window starts tomorrow rather than today. Care plans materialize visits at a fixed
    hour, so a window starting today produces a visit in the past whenever the suite runs
    after that hour — which would make the gap-detection tests pass or fail depending on the
    time of day.
    """
    _client_id, plan_id = await make_client_with_plan(tenant)
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date()
    async with tenant_session(tenant.agency_id) as session:
        plan = await session.get(CarePlan, plan_id)
        plan.authorized_tasks = [
            {"code": "bathing", "label": "Assist with bathing", "required_credential": "HHA"}
        ]
        await session.flush()
        visits = await scheduling.generate_visits(
            session,
            principal=tenant.principal(),
            care_plan=plan,
            window=scheduling.GenerationWindow(
                start=tomorrow,
                end=tomorrow + timedelta(days=7),
            ),
            duration_minutes=60,
        )
        assert visits[0].scheduled_start > datetime.now(UTC)
        return visits[0]


async def test_suggestions_are_explainable(tenant_a: TenantFixture, reference_data: None) -> None:
    visit = await _visit_for_matching(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        loaded = await session.get(ScheduledVisit, visit.id)
        suggestions = await matching.suggest_caregivers(session, visit=loaded)

    assert suggestions, "the seeded cleared caregiver should be suggestible"
    top = suggestions[0]
    assert 0.0 <= top.score <= 1.0
    assert top.factors, "every suggestion must show its reasoning"
    assert all("rationale" in f for f in top.factors)


async def test_uncleared_caregiver_is_never_suggested(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    """A name the scheduler cannot act on is worse than no name at all."""
    visit = await _visit_for_matching(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        caregiver.exclusion_check_status = ExclusionCheckStatus.not_run
        await session.flush()

        loaded = await session.get(ScheduledVisit, visit.id)
        suggestions = await matching.suggest_caregivers(session, visit=loaded)

    assert all(s.caregiver_id != tenant_a.caregiver_id for s in suggestions)


async def test_terminated_caregiver_is_never_suggested(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    visit = await _visit_for_matching(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        caregiver.employment_status = EmploymentStatus.terminated
        await session.flush()
        loaded = await session.get(ScheduledVisit, visit.id)
        suggestions = await matching.suggest_caregivers(session, visit=loaded)
    assert suggestions == []


async def test_double_booked_caregiver_is_not_suggested(
    tenant_a: TenantFixture, reference_data: None
) -> None:
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
        await scheduling.assign_caregiver(
            session, principal=tenant_a.principal(), visit=visits[0], caregiver=caregiver
        )
        # Make the second visit overlap the one they now hold.
        visits[1].scheduled_start = visits[0].scheduled_start
        visits[1].scheduled_end = visits[0].scheduled_end
        await session.flush()

        suggestions = await matching.suggest_caregivers(session, visit=visits[1])
    assert all(s.caregiver_id != tenant_a.caregiver_id for s in suggestions)


async def test_overtime_risk_is_warned_not_hidden(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    """Overtime is a cost to surface, not a hard block — the scheduler decides."""
    visit = await _visit_for_matching(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        loaded = await session.get(ScheduledVisit, visit.id)
        suggestions = await matching.suggest_caregivers(
            session, visit=loaded, overtime_threshold=0.5
        )

    assert suggestions, "an overtime risk must not remove the caregiver from the list"
    assert any("overtime" in w.lower() for w in suggestions[0].warnings)


async def test_suggestions_endpoint_is_audited(
    client, tenant_a: TenantFixture, reference_data: None
) -> None:
    """Ranking influences who is offered work, so the suggestion event is auditable."""
    from careos.core.audit import AuditAction
    from careos.modules.audit.models import AuditLog

    visit = await _visit_for_matching(tenant_a)
    response = await client.get(
        f"/v1/visits/{visit.id}/suggested-caregivers", headers=tenant_a.headers(Role.scheduler)
    )
    assert response.status_code == 200, response.text

    async with tenant_session(tenant_a.agency_id) as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == AuditAction.shift_suggestions_generated.value
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1


async def test_gaps_endpoint_resolves_before_the_visit_id_route(
    client, tenant_a: TenantFixture, reference_data: None
) -> None:
    """`/visits/gaps` must not be parsed as `/visits/{visit_id}`.

    Route declaration order decides this in FastAPI, so it is worth pinning: a reordering
    would turn this endpoint into a 422 on a malformed UUID.
    """
    await _visit_for_matching(tenant_a)
    response = await client.get(
        "/v1/visits/gaps?within_hours=720", headers=tenant_a.headers(Role.scheduler)
    )
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)


async def test_gaps_only_returns_unassigned_visits(
    client, tenant_a: TenantFixture, reference_data: None
) -> None:
    visit = await _visit_for_matching(tenant_a)
    headers = tenant_a.headers(Role.scheduler)

    before = await client.get("/v1/visits/gaps?within_hours=720", headers=headers)
    assert any(v["id"] == str(visit.id) for v in before.json())

    async with tenant_session(tenant_a.agency_id) as session:
        loaded = await session.get(ScheduledVisit, visit.id)
        caregiver = await session.get(Caregiver, tenant_a.caregiver_id)
        await scheduling.assign_caregiver(
            session, principal=tenant_a.principal(), visit=loaded, caregiver=caregiver
        )

    after = await client.get("/v1/visits/gaps?within_hours=720", headers=headers)
    assert all(v["id"] != str(visit.id) for v in after.json())


# --- Credentialing dashboard ----------------------------------------------------------------


async def test_credential_expiration_buckets(
    client, tenant_a: TenantFixture, reference_data: None
) -> None:
    """US-1.3.3: 60/30/7-day renewal horizons, plus already-expired."""
    today = datetime.now(UTC).date()
    async with tenant_session(tenant_a.agency_id) as session:
        for offset in (-5, 3, 20, 45, 200):
            await credentialing.add_credential(
                session,
                principal=tenant_a.principal(),
                caregiver_id=tenant_a.caregiver_id,
                credential_type="HHA",
                issuing_body="NY DOH",
                credential_number=str(uuid.uuid4())[:8],
                issue_date=today - timedelta(days=365),
                expiration_date=today + timedelta(days=offset),
                verification_status=VerificationStatus.verified,
            )

    response = await client.get("/v1/reports/credential-expirations", headers=tenant_a.headers())
    assert response.status_code == 200, response.text
    rows = response.json()

    # The credential expiring in 200 days is beyond the 60-day horizon.
    assert len(rows) == 4
    by_days = {r["days_until_expiry"]: r for r in rows}
    assert by_days[-5]["already_expired"] is True
    assert by_days[3]["bucket"] == 7
    assert by_days[20]["bucket"] == 30
    assert by_days[45]["bucket"] == 60


async def test_expired_credentials_are_surfaced_not_filtered(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    """An already-expired credential is the most urgent case, not the least relevant."""
    today = datetime.now(UTC).date()
    async with tenant_session(tenant_a.agency_id) as session:
        await credentialing.add_credential(
            session,
            principal=tenant_a.principal(),
            caregiver_id=tenant_a.caregiver_id,
            credential_type="CPR",
            issuing_body=None,
            credential_number=None,
            issue_date=None,
            expiration_date=today - timedelta(days=90),
            verification_status=VerificationStatus.verified,
        )
        rows = await credentialing.expiring_credentials(session)

    assert len(rows) == 1
    assert rows[0].already_expired is True
    assert rows[0].days_until_expiry == -90


async def test_credentials_are_tenant_scoped(
    client, tenant_a: TenantFixture, tenant_b: TenantFixture, reference_data: None
) -> None:
    async with tenant_session(tenant_a.agency_id) as session:
        await credentialing.add_credential(
            session,
            principal=tenant_a.principal(),
            caregiver_id=tenant_a.caregiver_id,
            credential_type="HHA",
            issuing_body=None,
            credential_number=None,
            issue_date=None,
            expiration_date=datetime.now(UTC).date() + timedelta(days=10),
            verification_status=VerificationStatus.verified,
        )

    response = await client.get("/v1/reports/credential-expirations", headers=tenant_b.headers())
    assert response.status_code == 200
    assert response.json() == []
