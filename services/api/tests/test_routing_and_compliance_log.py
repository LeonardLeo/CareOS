"""Routing adapter and compliance review log tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from careos.db.session import tenant_session
from careos.integrations.routing.base import (
    GeoPoint,
    HaversineRoutingAdapter,
    RoutingAdapter,
    TravelEstimate,
    haversine_miles,
)
from careos.integrations.routing.registry import (
    available_adapter_keys,
    get_routing_adapter,
    register_adapter,
)
from careos.modules.agency.models import Role
from careos.modules.audit.compliance_log import record_review, review_status
from careos.modules.audit.compliance_log_models import (
    REVIEW_CADENCE_DAYS,
    ReviewOutcome,
    ReviewType,
)
from tests.conftest import TenantFixture

# --- Routing --------------------------------------------------------------------------------


def test_haversine_matches_a_known_distance() -> None:
    """Manhattan to Brooklyn, roughly 4 miles straight-line."""
    miles = haversine_miles(GeoPoint(40.7580, -73.9855), GeoPoint(40.6782, -73.9442))
    assert 5 < miles < 7


def test_identical_points_are_zero() -> None:
    assert haversine_miles(GeoPoint(40.7, -74.0), GeoPoint(40.7, -74.0)) == pytest.approx(0.0)


async def test_estimate_applies_circuity_and_reports_uncertainty() -> None:
    """Road distance exceeds straight-line, and the estimate says it is an estimate."""
    adapter = HaversineRoutingAdapter()
    origin, destination = GeoPoint(40.7580, -73.9855), GeoPoint(40.6782, -73.9442)
    straight = haversine_miles(origin, destination)

    estimate = await adapter.estimate(origin, destination)
    assert estimate.miles > straight
    assert estimate.minutes > 0
    assert estimate.is_estimate is True
    assert "not a routed drive time" in estimate.basis


async def test_estimate_duration_tracks_distance() -> None:
    adapter = HaversineRoutingAdapter(average_speed_mph=30)
    near = await adapter.estimate(GeoPoint(40.70, -74.00), GeoPoint(40.71, -74.00))
    far = await adapter.estimate(GeoPoint(40.70, -74.00), GeoPoint(41.20, -74.00))
    assert far.minutes > near.minutes
    assert far.hours == pytest.approx(far.minutes / 60)


def test_invalid_speed_is_rejected() -> None:
    with pytest.raises(ValueError):
        HaversineRoutingAdapter(average_speed_mph=0)


async def test_estimate_many_matches_individual_estimates() -> None:
    adapter = HaversineRoutingAdapter()
    origin = GeoPoint(40.7, -74.0)
    destinations = [GeoPoint(40.75, -73.98), GeoPoint(40.65, -73.95)]

    batch = await adapter.estimate_many(origin, destinations)
    individual = [await adapter.estimate(origin, d) for d in destinations]
    assert [e.miles for e in batch] == [e.miles for e in individual]


def test_registry_returns_the_configured_adapter() -> None:
    assert isinstance(get_routing_adapter(), HaversineRoutingAdapter)
    assert HaversineRoutingAdapter.adapter_key in available_adapter_keys()


def test_a_provider_can_be_registered() -> None:
    """Swapping in a real routing provider must not touch the scheduling module."""

    class FakeProvider(RoutingAdapter):
        adapter_key = "fake_provider"

        async def estimate(self, origin: GeoPoint, destination: GeoPoint) -> TravelEstimate:
            return TravelEstimate(miles=1.0, minutes=5.0, is_estimate=False, basis="fake routed")

    register_adapter(FakeProvider)
    assert "fake_provider" in available_adapter_keys()


async def test_matching_uses_the_injected_routing_adapter(
    tenant_a: TenantFixture, reference_data: None
) -> None:
    """The scheduler talks to the interface, not to an implementation."""
    from careos.modules.scheduling import matching
    from tests.test_recruiting_and_matching import _visit_for_matching

    calls: list[tuple[GeoPoint, GeoPoint]] = []

    class RecordingAdapter(RoutingAdapter):
        adapter_key = "recording"

        async def estimate(self, origin: GeoPoint, destination: GeoPoint) -> TravelEstimate:
            calls.append((origin, destination))
            return TravelEstimate(miles=2.0, minutes=90.0, is_estimate=False, basis="recorded")

    visit = await _visit_for_matching(tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        from careos.modules.scheduling.models import ScheduledVisit

        loaded = await session.get(ScheduledVisit, visit.id)
        suggestions = await matching.suggest_caregivers(
            session, visit=loaded, routing=RecordingAdapter()
        )

    assert calls, "matching should have consulted the routing adapter"
    # 90 minutes is beyond the 45-minute threshold, so the travel warning should fire.
    assert any("travel" in w.lower() for w in suggestions[0].warnings)


# --- Compliance review log ------------------------------------------------------------------


async def test_never_performed_reviews_are_reported_as_gaps(tenant_a: TenantFixture) -> None:
    """An absent review must not read as a clean bill of health."""
    async with tenant_session(tenant_a.agency_id) as session:
        statuses = await review_status(session)

    by_type = {s.review_type: s for s in statuses}
    # Every review type in the Section 9 cadence is enumerated, not just those with rows.
    assert set(by_type) == {t.value for t in ReviewType}
    assert all(s.never_performed for s in statuses)

    bias = by_type[ReviewType.ai_hiring_bias_audit.value]
    assert bias.never_performed is True
    assert bias.is_overdue is True, "a scheduled review never performed is overdue"


async def test_event_triggered_reviews_are_not_overdue_on_a_schedule(
    tenant_a: TenantFixture,
) -> None:
    """A review triggered by entering a new state has no calendar to be late against."""
    async with tenant_session(tenant_a.agency_id) as session:
        statuses = {s.review_type: s for s in await review_status(session)}

    assert REVIEW_CADENCE_DAYS[ReviewType.new_state_entry] is None
    assert statuses[ReviewType.new_state_entry.value].is_overdue is False


async def test_recording_a_review_sets_the_next_due_date(tenant_a: TenantFixture) -> None:
    today = datetime.now(UTC).date()
    async with tenant_session(tenant_a.agency_id) as session:
        review = await record_review(
            session,
            principal=tenant_a.principal(),
            agency_id=tenant_a.agency_id,
            review_type=ReviewType.healthcare_counsel,
            outcome=ReviewOutcome.passed,
            performed_by="Example Health Law LLP",
            summary="Reviewed EVV and HIPAA implementation",
        )
        assert review.next_due_on == today + timedelta(days=365)

        statuses = {s.review_type: s for s in await review_status(session)}

    counsel = statuses[ReviewType.healthcare_counsel.value]
    assert counsel.never_performed is False
    assert counsel.last_outcome == "passed"
    assert counsel.is_overdue is False


async def test_an_old_review_becomes_overdue(tenant_a: TenantFixture) -> None:
    long_ago = datetime.now(UTC).date() - timedelta(days=400)
    async with tenant_session(tenant_a.agency_id) as session:
        await record_review(
            session,
            principal=tenant_a.principal(),
            agency_id=tenant_a.agency_id,
            review_type=ReviewType.evv_vendor_review,
            outcome=ReviewOutcome.passed,
            performed_by="Ops",
            performed_on=long_ago,
        )
        statuses = {s.review_type: s for s in await review_status(session)}

    assert statuses[ReviewType.evv_vendor_review.value].is_overdue is True


async def test_a_newer_review_supersedes_the_previous_one(tenant_a: TenantFixture) -> None:
    """History is kept; only the current standing changes."""
    async with tenant_session(tenant_a.agency_id) as session:
        await record_review(
            session,
            principal=tenant_a.principal(),
            agency_id=tenant_a.agency_id,
            review_type=ReviewType.ai_hiring_bias_audit,
            outcome=ReviewOutcome.failed,
            performed_by="automated",
            performed_on=datetime.now(UTC).date() - timedelta(days=10),
            model_version="v1",
        )
        await record_review(
            session,
            principal=tenant_a.principal(),
            agency_id=tenant_a.agency_id,
            review_type=ReviewType.ai_hiring_bias_audit,
            outcome=ReviewOutcome.passed,
            performed_by="automated",
            model_version="v2",
        )
        statuses = {s.review_type: s for s in await review_status(session)}

    assert statuses[ReviewType.ai_hiring_bias_audit.value].last_outcome == "passed"

    # The superseded row is retained.
    from sqlalchemy import func, select

    from careos.modules.audit.compliance_log_models import ComplianceReview

    async with tenant_session(tenant_a.agency_id) as session:
        total = (
            await session.execute(select(func.count()).select_from(ComplianceReview))
        ).scalar_one()
    assert total == 2


async def test_scoped_reviews_do_not_supersede_each_other(tenant_a: TenantFixture) -> None:
    """A consent-law review for New York says nothing about Texas."""
    from sqlalchemy import select

    from careos.modules.audit.compliance_log_models import ComplianceReview

    async with tenant_session(tenant_a.agency_id) as session:
        for state in ("NY", "TX"):
            await record_review(
                session,
                principal=tenant_a.principal(),
                agency_id=tenant_a.agency_id,
                review_type=ReviewType.consent_law_state,
                outcome=ReviewOutcome.passed,
                performed_by="Counsel",
                scope=state,
            )
        active = (
            (
                await session.execute(
                    select(ComplianceReview).where(ComplianceReview.superseded_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
    assert {r.scope for r in active} == {"NY", "TX"}


async def test_compliance_reviews_endpoint(client, tenant_a: TenantFixture) -> None:
    response = await client.get(
        f"/v1/agencies/{tenant_a.agency_id}/compliance-reviews",
        headers=tenant_a.headers(Role.owner_admin),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == len(ReviewType)
    assert all(row["never_performed"] for row in body)


async def test_compliance_reviews_are_tenant_scoped(
    client, tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    async with tenant_session(tenant_a.agency_id) as session:
        await record_review(
            session,
            principal=tenant_a.principal(),
            agency_id=tenant_a.agency_id,
            review_type=ReviewType.healthcare_counsel,
            outcome=ReviewOutcome.passed,
            performed_by="Counsel",
        )

    response = await client.get(
        f"/v1/agencies/{tenant_b.agency_id}/compliance-reviews",
        headers=tenant_b.headers(Role.owner_admin),
    )
    assert response.status_code == 200
    statuses = {r["review_type"]: r for r in response.json()}
    assert statuses[ReviewType.healthcare_counsel.value]["never_performed"] is True
