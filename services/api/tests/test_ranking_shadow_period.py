"""The ranking shadow period.

`06_Compliance_and_Regulatory_Requirements.md` Section 5 requires a bias audit before the
ranking model influences hiring. The audit needs outcomes; outcomes need the model to have
influenced hiring. `13_Phase_1_Launch_Plan.md` 6.3 resolves that circle by running the scorer
and withholding its output, so the first cohort produces auditable outcomes that no
decision-maker ever saw a score for.

That only works if the withholding is total. A blanked number at the top of a list sorted by
that number is still a recommendation, so most of these tests are about ordering rather than
about the number itself.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from careos.core.errors import ConflictError
from careos.db.session import tenant_session
from careos.modules.agency.models import Agency, Role
from careos.modules.audit import compliance_log
from careos.modules.audit.compliance_log_models import ReviewOutcome, ReviewType
from careos.modules.audit.models import AuditLog
from careos.modules.recruiting import service as recruiting
from careos.modules.recruiting.models import ApplicantProfile, JobPosting
from tests.conftest import TenantFixture


async def _posting_with_applicants(tenant: TenantFixture) -> uuid.UUID:
    """One posting and three applicants whose apply order is the reverse of their fit.

    Built that way on purpose: if application order and score order coincided, a test could
    not tell a withheld ranking from a displayed one.
    """
    async with tenant_session(tenant.agency_id) as session:
        posting = JobPosting(
            agency_id=tenant.agency_id,
            title="Home Health Aide",
            required_credential_types=["HHA", "CPR"],
            service_state="NY",
        )
        session.add(posting)
        await session.flush()

        # Worst fit applies first, best fit last.
        for index, (name, credentials) in enumerate(
            [
                ("First Applicant Weakest", []),
                ("Second Applicant Middling", ["HHA"]),
                ("Third Applicant Strongest", ["HHA", "CPR"]),
            ]
        ):
            session.add(
                ApplicantProfile(
                    agency_id=tenant.agency_id,
                    job_posting_id=posting.id,
                    source="direct",
                    full_name=name,
                    claimed_credentials=credentials,
                    availability={"days": ["mon", "tue", "wed", "thu", "fri"]},
                    created_at=datetime.now(UTC) + timedelta(seconds=index),
                )
            )
        await session.flush()
        return posting.id


async def _record_bias_audit(tenant: TenantFixture, outcome: ReviewOutcome) -> None:
    async with tenant_session(tenant.agency_id) as session:
        await compliance_log.record_review(
            session,
            principal=tenant.principal(),
            agency_id=tenant.agency_id,
            review_type=ReviewType.ai_hiring_bias_audit,
            outcome=outcome,
            performed_by="Employment counsel",
            performed_on=date.today(),
            model_version="deterministic-v1",
        )


# --- The default -------------------------------------------------------------------------


async def test_a_new_agency_starts_in_the_shadow_period(tenant_a: TenantFixture) -> None:
    """The safe state has to be the one nobody has to remember to choose."""
    async with tenant_session(tenant_a.agency_id) as session:
        agency = await session.get(Agency, tenant_a.agency_id)
        assert agency is not None
        assert agency.ranking_display_enabled is False
        assert agency.ranking_display_enabled_at is None


# --- What is withheld --------------------------------------------------------------------


async def test_scores_are_withheld_from_the_api_during_the_shadow_period(
    client, tenant_a: TenantFixture
) -> None:
    posting_id = await _posting_with_applicants(tenant_a)

    response = await client.get(
        f"/v1/job-postings/{posting_id}/applicants", headers=tenant_a.headers(Role.owner_admin)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body, "no applicants came back at all"
    for applicant in body:
        assert applicant["ranking_score"] is None
        assert applicant["ranking_factors"] == []
        assert applicant["ranking_model_version"] is None
        assert applicant["ranking_displayed"] is False


async def test_the_list_order_does_not_leak_the_ranking(client, tenant_a: TenantFixture) -> None:
    """The top of a list is a recommendation whether or not it carries a number.

    This is the test that would have caught the obvious half-fix: blanking the score fields
    and leaving the ORDER BY alone.
    """
    posting_id = await _posting_with_applicants(tenant_a)

    response = await client.get(
        f"/v1/job-postings/{posting_id}/applicants", headers=tenant_a.headers(Role.owner_admin)
    )
    names = [a["full_name"] for a in response.json()]
    assert names == [
        "First Applicant Weakest",
        "Second Applicant Middling",
        "Third Applicant Strongest",
    ], "applicants came back in an order derived from the model"


async def test_the_read_only_view_withholds_the_ranking_too(
    client, tenant_a: TenantFixture
) -> None:
    """`?rank=false` takes a different code path, and it is the easy one to forget."""
    posting_id = await _posting_with_applicants(tenant_a)
    # Score them once through the ranking path so there is something stored to leak.
    await client.get(
        f"/v1/job-postings/{posting_id}/applicants", headers=tenant_a.headers(Role.owner_admin)
    )

    response = await client.get(
        f"/v1/job-postings/{posting_id}/applicants?rank=false",
        headers=tenant_a.headers(Role.owner_admin),
    )
    body = response.json()
    assert [a["full_name"] for a in body] == [
        "First Applicant Weakest",
        "Second Applicant Middling",
        "Third Applicant Strongest",
    ]
    assert all(a["ranking_score"] is None for a in body)


async def test_the_stage_change_response_withholds_the_ranking(
    client, tenant_a: TenantFixture
) -> None:
    """Every endpoint returning an applicant is a way for the score to reach a screen."""
    posting_id = await _posting_with_applicants(tenant_a)
    await client.get(
        f"/v1/job-postings/{posting_id}/applicants", headers=tenant_a.headers(Role.owner_admin)
    )
    async with tenant_session(tenant_a.agency_id) as session:
        applicant_id = (await session.execute(select(ApplicantProfile.id).limit(1))).scalars().one()

    response = await client.post(
        f"/v1/applicants/{applicant_id}/stage",
        json={"stage": "screened"},
        headers=tenant_a.headers(Role.owner_admin),
    )
    assert response.status_code == 200, response.text
    assert response.json()["ranking_score"] is None
    assert response.json()["ranking_displayed"] is False


# --- What is not withheld ----------------------------------------------------------------


async def test_the_scorer_still_runs_and_still_persists(client, tenant_a: TenantFixture) -> None:
    """A shadow period that skipped scoring would end with nothing to audit.

    This is the property that makes the whole approach work, and it is the one most likely to
    be broken by someone "optimising away" a computation whose result is thrown out.
    """
    posting_id = await _posting_with_applicants(tenant_a)
    await client.get(
        f"/v1/job-postings/{posting_id}/applicants", headers=tenant_a.headers(Role.owner_admin)
    )

    async with tenant_session(tenant_a.agency_id) as session:
        rows = (await session.execute(select(ApplicantProfile))).scalars().all()
    assert rows
    for row in rows:
        assert row.ranking_score is not None, "the scorer did not run during the shadow period"
        assert row.ranking_factors, "a score was stored with no explanatory factors"
        assert row.ranking_model_version == "deterministic-v1"


async def test_the_shadow_period_is_evidenced_in_the_audit_log(
    client, tenant_a: TenantFixture
) -> None:
    """ "We computed and withheld" is worth nothing as a claim about a config value.

    The audit row is written at the moment it was true, which is what an employment-counsel
    review can actually check.
    """
    posting_id = await _posting_with_applicants(tenant_a)
    await client.get(
        f"/v1/job-postings/{posting_id}/applicants", headers=tenant_a.headers(Role.owner_admin)
    )

    async with tenant_session(tenant_a.agency_id) as session:
        rows = (
            (await session.execute(select(AuditLog).where(AuditLog.action == "applicant.ranked")))
            .scalars()
            .all()
        )
    assert rows
    assert rows[-1].after_state["ranking_displayed"] is False


# --- Ending the shadow period ------------------------------------------------------------


async def test_display_cannot_be_enabled_without_a_bias_audit(tenant_a: TenantFixture) -> None:
    async with tenant_session(tenant_a.agency_id) as session:
        with pytest.raises(ConflictError, match="bias audit"):
            await recruiting.enable_ranking_display(session, principal=tenant_a.principal())


async def test_a_failed_bias_audit_does_not_permit_display(tenant_a: TenantFixture) -> None:
    await _record_bias_audit(tenant_a, ReviewOutcome.failed)
    async with tenant_session(tenant_a.agency_id) as session:
        with pytest.raises(ConflictError):
            await recruiting.enable_ranking_display(session, principal=tenant_a.principal())


async def test_an_inconclusive_bias_audit_does_not_permit_display(
    tenant_a: TenantFixture,
) -> None:
    """ "We could not tell" is not the same finding as "we looked and it was fine".

    A fairness audit is usually inconclusive because the sample was too small — which is
    exactly the situation at the end of a first cohort, and exactly when the temptation to
    treat it as a pass is strongest.
    """
    await _record_bias_audit(tenant_a, ReviewOutcome.inconclusive)
    async with tenant_session(tenant_a.agency_id) as session:
        with pytest.raises(ConflictError):
            await recruiting.enable_ranking_display(session, principal=tenant_a.principal())


async def test_a_passing_bias_audit_permits_display(tenant_a: TenantFixture) -> None:
    await _record_bias_audit(tenant_a, ReviewOutcome.passed)
    async with tenant_session(tenant_a.agency_id) as session:
        agency = await recruiting.enable_ranking_display(session, principal=tenant_a.principal())
        assert agency.ranking_display_enabled is True
        assert agency.ranking_display_enabled_at is not None


async def test_a_passing_audit_with_findings_permits_display(tenant_a: TenantFixture) -> None:
    """Findings are the normal outcome of a real audit; requiring a spotless one means never."""
    await _record_bias_audit(tenant_a, ReviewOutcome.passed_with_findings)
    async with tenant_session(tenant_a.agency_id) as session:
        agency = await recruiting.enable_ranking_display(session, principal=tenant_a.principal())
        assert agency.ranking_display_enabled is True


async def test_enabling_display_records_the_audit_it_was_granted_on(
    tenant_a: TenantFixture,
) -> None:
    """So "the audit came first" is checkable afterwards rather than asserted."""
    await _record_bias_audit(tenant_a, ReviewOutcome.passed)
    async with tenant_session(tenant_a.agency_id) as session:
        await recruiting.enable_ranking_display(session, principal=tenant_a.principal())

    async with tenant_session(tenant_a.agency_id) as session:
        row = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "agency.ranking_display_enabled")
                )
            )
            .scalars()
            .one()
        )
    assert row.after_state["bias_audit_outcome"] == "passed"
    assert row.after_state["bias_audit_performed_on"] == date.today().isoformat()


# --- After the shadow period -------------------------------------------------------------


async def test_scores_and_score_order_return_once_display_is_enabled(
    client, tenant_a: TenantFixture
) -> None:
    """The feature has to actually work at the end of this, not just be safely disabled."""
    posting_id = await _posting_with_applicants(tenant_a)
    await _record_bias_audit(tenant_a, ReviewOutcome.passed)
    async with tenant_session(tenant_a.agency_id) as session:
        await recruiting.enable_ranking_display(session, principal=tenant_a.principal())

    response = await client.get(
        f"/v1/job-postings/{posting_id}/applicants", headers=tenant_a.headers(Role.owner_admin)
    )
    body = response.json()
    assert body[0]["full_name"] == "Third Applicant Strongest", "score order did not return"
    assert body[0]["ranking_score"] is not None
    assert body[0]["ranking_factors"]
    assert body[0]["ranking_displayed"] is True


async def test_one_agency_leaving_the_shadow_period_does_not_move_another(
    client, tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    """Agencies join at different times; one's first cohort is not evidence about another's."""
    b_posting = await _posting_with_applicants(tenant_b)
    await _record_bias_audit(tenant_a, ReviewOutcome.passed)
    async with tenant_session(tenant_a.agency_id) as session:
        await recruiting.enable_ranking_display(session, principal=tenant_a.principal())

    response = await client.get(
        f"/v1/job-postings/{b_posting}/applicants", headers=tenant_b.headers(Role.owner_admin)
    )
    assert all(a["ranking_displayed"] is False for a in response.json())


# --- Through the API ---------------------------------------------------------------------


async def test_the_endpoint_is_owner_admin_only(client, tenant_a: TenantFixture) -> None:
    await _record_bias_audit(tenant_a, ReviewOutcome.passed)
    for role in (Role.scheduler, Role.auditor, Role.clinical_supervisor):
        refused = await client.post(
            f"/v1/agencies/{tenant_a.agency_id}/ranking-display",
            headers=tenant_a.headers(role),
        )
        assert refused.status_code == 403, f"{role} could end the shadow period"

    allowed = await client.post(
        f"/v1/agencies/{tenant_a.agency_id}/ranking-display",
        headers=tenant_a.headers(Role.owner_admin),
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["ranking_display_enabled"] is True


async def test_one_agency_cannot_end_anothers_shadow_period(
    client, tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    response = await client.post(
        f"/v1/agencies/{tenant_b.agency_id}/ranking-display",
        headers=tenant_a.headers(Role.owner_admin),
    )
    assert response.status_code == 404
