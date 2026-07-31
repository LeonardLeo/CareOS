"""Background screening: what it must refuse to do.

`assert_assignable` reads one field, `exclusion_check_status`, and refuses publicly-funded
assignment unless it says `cleared`. This module is now the main thing that writes it, which
makes almost every test here a test of a *negative*: the conditions under which a caregiver
must not become assignable.

That asymmetry is the point. A screening that wrongly blocks someone is a phone call to an
administrator. A screening that wrongly clears someone puts an excluded individual on a
Medicaid-billed visit, which is a false-claims exposure discovered in an audit months later.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from careos.config import Settings, validate_settings
from careos.core.errors import ConflictError, ScreeningUnavailableError
from careos.db.session import tenant_session
from careos.integrations.screening.adapters.loopback import (
    VENDOR_STATUS_MAP,
    LoopbackScreeningAdapter,
)
from careos.integrations.screening.base import (
    ScreeningCheck,
    ScreeningError,
    ScreeningResult,
    ScreeningSubject,
    ScreeningVerdict,
    verdict_from_vendor_status,
)
from careos.integrations.screening.registry import get_screening_adapter
from careos.modules.agency.models import Role
from careos.modules.audit.models import AuditLog
from careos.modules.credentialing import screening
from careos.modules.credentialing.models import (
    Caregiver,
    EmploymentStatus,
    ExclusionCheckStatus,
    ScreeningRequest,
)
from careos.modules.scheduling.models import ComplianceException
from careos.modules.webhooks.models import WebhookDelivery
from tests.conftest import TenantFixture

# --- The verdict mapping -----------------------------------------------------------------
#
# The translation from a vendor's status vocabulary to ours is the single place a typo turns
# into a cleared exclusion. It is tested on its own, without a database, because it is the
# smallest thing that can be wrong and the most expensive.


def test_unknown_vendor_status_raises_rather_than_defaulting() -> None:
    """A status nobody has mapped must stop the pipeline, not pick a verdict.

    Vendors add statuses. If an unmapped one fell through to `clear`, the first time a
    provider introduced e.g. "manual_review_required" every caregiver in review would become
    assignable to Medicaid work.
    """
    with pytest.raises(ScreeningError):
        verdict_from_vendor_status("manual_review_required", mapping=VENDOR_STATUS_MAP)


def test_known_vendor_statuses_map_to_the_expected_verdicts() -> None:
    assert verdict_from_vendor_status("no_records_found", mapping=VENDOR_STATUS_MAP) is (
        ScreeningVerdict.clear
    )
    assert verdict_from_vendor_status("records_found", mapping=VENDOR_STATUS_MAP) is (
        ScreeningVerdict.flagged
    )
    assert verdict_from_vendor_status("in_progress", mapping=VENDOR_STATUS_MAP) is (
        ScreeningVerdict.pending
    )


def test_a_final_result_must_say_when_it_completed() -> None:
    """`exclusion_checked_at` is what the re-screening schedule runs off.

    A final verdict with no timestamp would clear a caregiver permanently: the re-screen
    query looks for a stale `exclusion_checked_at`, and NULL is not stale.
    """
    with pytest.raises(ValueError):
        ScreeningResult(vendor_request_id="x", verdict=ScreeningVerdict.clear)


def test_the_verdict_mapping_never_turns_a_non_clear_verdict_into_a_clearance() -> None:
    """Exhaustive over the enum, so a fourth verdict added later cannot default to cleared.

    `record_result` guards on `is_final` before this runs, so the pending case here is a
    second line. It is asserted anyway: this is the function that decides who may work a
    Medicaid-billed visit, and every branch of it should be stated.
    """
    for verdict in ScreeningVerdict:
        result = ScreeningResult(
            vendor_request_id="x",
            verdict=verdict,
            completed_at=None if verdict is ScreeningVerdict.pending else datetime.now(UTC),
        )
        mapped = screening._exclusion_status_for(result)
        if verdict is ScreeningVerdict.clear:
            assert mapped is ExclusionCheckStatus.cleared
        else:
            assert mapped is not ExclusionCheckStatus.cleared, (
                f"verdict {verdict} would clear a caregiver"
            )


async def test_a_second_adapter_instance_can_resolve_the_first_instances_order() -> None:
    """The deployment topology: the API orders, and a separate worker process polls.

    The first version of the loopback adapter kept its orders in an instance attribute. Every
    test passed, and running the real worker produced "No such loopback screening request" on
    the first tick — the worker's adapter had never seen the order and never could. A real
    vendor adapter holds no state; it asks the vendor about an id. This is the test that says
    the fake has to behave the same way.
    """
    ordering_instance = LoopbackScreeningAdapter()
    polling_instance = LoopbackScreeningAdapter()

    subject = ScreeningSubject(caregiver_id=uuid.uuid4(), legal_name="Ada Newhire")
    order = await ordering_instance.order(subject, (ScreeningCheck.exclusion_list,))
    result = await polling_instance.fetch(order.vendor_request_id)
    assert result.verdict is ScreeningVerdict.clear


async def test_a_request_id_this_adapter_did_not_mint_is_refused() -> None:
    """A foreign or malformed reference must not resolve to a verdict."""
    adapter = LoopbackScreeningAdapter()
    for bogus in ("some-other-vendor-ref", "loopback-nonsense-x-y", "loopback"):
        with pytest.raises(ScreeningError):
            await adapter.fetch(bogus)


# --- The registry ------------------------------------------------------------------------


def test_loopback_adapter_is_refused_outside_local_and_test() -> None:
    """It clears everyone whose name lacks a marker. That is a fabricated check, not a weak one."""
    from careos.config import get_settings

    get_settings.cache_clear()
    import os

    previous = os.environ.get("CAREOS_ENVIRONMENT")
    os.environ["CAREOS_ENVIRONMENT"] = "staging"
    get_settings.cache_clear()
    try:
        with pytest.raises(ScreeningUnavailableError):
            get_screening_adapter()
    finally:
        if previous is None:
            del os.environ["CAREOS_ENVIRONMENT"]
        else:
            os.environ["CAREOS_ENVIRONMENT"] = previous
        get_settings.cache_clear()


def test_production_refuses_to_boot_on_the_loopback_screening_adapter() -> None:
    # Every other production requirement is met, so the guard under test is the one that
    # fires. `validate_settings` raises on the first unmet requirement, and a config missing
    # several would pass this test for the wrong reason.
    settings = Settings(
        environment="production",
        jwt_secret="a-real-secret-value-for-production-use",
        evv_use_sandbox=False,
        cors_allowed_origins=["https://admin.example.com"],
        rate_limit_backend="redis",
        metrics_token="set-in-the-secrets-manager",
        mfa_required=True,
        screening_adapter="loopback",
    )
    with pytest.raises(RuntimeError, match="CAREOS_SCREENING_ADAPTER"):
        validate_settings(settings)

    # And a real vendor key boots.
    assert validate_settings(settings.model_copy(update={"screening_adapter": "vendor"}))


# --- Ordering ----------------------------------------------------------------------------


async def _caregiver(tenant: TenantFixture, legal_name: str) -> uuid.UUID:
    async with tenant_session(tenant.agency_id) as session:
        caregiver = Caregiver(
            agency_id=tenant.agency_id,
            legal_name=legal_name,
            employment_status=EmploymentStatus.onboarding,
            exclusion_check_status=ExclusionCheckStatus.not_run,
        )
        session.add(caregiver)
        await session.flush()
        return caregiver.id


async def test_ordering_a_screening_does_not_clear_anybody(tenant_a: TenantFixture) -> None:
    """202 means "a search is running", and the caregiver stays unassignable until it answers.

    The most tempting bug in this whole module is treating a successful *order* as a
    successful *check*.
    """
    caregiver_id = await _caregiver(tenant_a, "Ada Newhire")
    adapter = LoopbackScreeningAdapter(complete_immediately=False)

    async with tenant_session(tenant_a.agency_id) as session:
        request = await screening.order_screening(
            session,
            agency_id=tenant_a.agency_id,
            caregiver_id=caregiver_id,
            principal=tenant_a.principal(),
            adapter=adapter,
        )
        assert request.status == screening.STATUS_PENDING
        caregiver = await session.get(Caregiver, caregiver_id)
        assert caregiver is not None
        assert caregiver.exclusion_check_status is ExclusionCheckStatus.not_run


async def test_a_second_order_while_one_is_outstanding_is_refused(
    tenant_a: TenantFixture,
) -> None:
    """These are billed per search and touch a real person's records."""
    caregiver_id = await _caregiver(tenant_a, "Ada Newhire")
    adapter = LoopbackScreeningAdapter(complete_immediately=False)

    async with tenant_session(tenant_a.agency_id) as session:
        await screening.order_screening(
            session,
            agency_id=tenant_a.agency_id,
            caregiver_id=caregiver_id,
            principal=tenant_a.principal(),
            adapter=adapter,
        )
        with pytest.raises(ConflictError):
            await screening.order_screening(
                session,
                agency_id=tenant_a.agency_id,
                caregiver_id=caregiver_id,
                principal=tenant_a.principal(),
                adapter=adapter,
            )
    assert len(adapter.orders) == 1, "the vendor was asked twice"


async def test_the_vendor_is_sent_only_what_a_search_needs(tenant_a: TenantFixture) -> None:
    """Identity data leaves the system here. The narrowness of the subject is the control."""
    caregiver_id = await _caregiver(tenant_a, "Ada Newhire")
    adapter = LoopbackScreeningAdapter()

    async with tenant_session(tenant_a.agency_id) as session:
        await screening.order_screening(
            session,
            agency_id=tenant_a.agency_id,
            caregiver_id=caregiver_id,
            principal=tenant_a.principal(),
            adapter=adapter,
        )

    sent = adapter.orders[0]
    assert sent["legal_name"] == "Ada Newhire"
    # No full SSN is ever assembled, so no adapter can forward one.
    assert sent["ssn_last4"] is None
    assert set(sent) == {
        "vendor_request_id",
        "caregiver_id",
        "legal_name",
        "date_of_birth",
        "ssn_last4",
        "checks",
    }


async def test_a_vendor_that_refuses_the_order_leaves_a_record(tenant_a: TenantFixture) -> None:
    """An agency that cannot screen anyone must be able to see the attempts."""
    caregiver_id = await _caregiver(tenant_a, "Ada Newhire")
    adapter = LoopbackScreeningAdapter()

    async with tenant_session(tenant_a.agency_id) as session:
        with pytest.raises(ScreeningUnavailableError):
            await screening.order_screening(
                session,
                agency_id=tenant_a.agency_id,
                caregiver_id=caregiver_id,
                principal=tenant_a.principal(),
                adapter=adapter,
                checks=(),  # the adapter rejects an empty bundle
            )

    async with tenant_session(tenant_a.agency_id) as session:
        rows = (
            (
                await session.execute(
                    select(ScreeningRequest).where(ScreeningRequest.caregiver_id == caregiver_id)
                )
            )
            .scalars()
            .all()
        )
    assert [r.status for r in rows] == [screening.STATUS_FAILED]


# --- Resolving ---------------------------------------------------------------------------


async def _order_and_poll(
    tenant: TenantFixture, caregiver_id: uuid.UUID, adapter: LoopbackScreeningAdapter
) -> None:
    async with tenant_session(tenant.agency_id) as session:
        await screening.order_screening(
            session,
            agency_id=tenant.agency_id,
            caregiver_id=caregiver_id,
            principal=tenant.principal(),
            adapter=adapter,
        )


async def test_a_clear_verdict_clears_the_caregiver(
    tenant_a: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caregiver_id = await _caregiver(tenant_a, "Ada Newhire")
    adapter = LoopbackScreeningAdapter()
    monkeypatch.setattr(screening, "get_screening_adapter", lambda: adapter)

    await _order_and_poll(tenant_a, caregiver_id, adapter)
    run = await screening.poll_outstanding(tenant_a.agency_id)

    assert run.resolved == 1
    async with tenant_session(tenant_a.agency_id) as session:
        caregiver = await session.get(Caregiver, caregiver_id)
        assert caregiver is not None
        assert caregiver.exclusion_check_status is ExclusionCheckStatus.cleared
        assert caregiver.exclusion_checked_at is not None


async def test_a_pending_verdict_changes_nothing(
    tenant_a: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Still looking" is an answer, and it is not "cleared"."""
    caregiver_id = await _caregiver(tenant_a, "Ada Newhire")
    adapter = LoopbackScreeningAdapter(complete_immediately=False)
    monkeypatch.setattr(screening, "get_screening_adapter", lambda: adapter)

    await _order_and_poll(tenant_a, caregiver_id, adapter)
    run = await screening.poll_outstanding(tenant_a.agency_id)

    assert run.considered == 1
    assert run.resolved == 0
    async with tenant_session(tenant_a.agency_id) as session:
        caregiver = await session.get(Caregiver, caregiver_id)
        assert caregiver is not None
        assert caregiver.exclusion_check_status is ExclusionCheckStatus.not_run
        outstanding = (
            (
                await session.execute(
                    select(ScreeningRequest).where(ScreeningRequest.caregiver_id == caregiver_id)
                )
            )
            .scalars()
            .all()
        )
        assert [r.status for r in outstanding] == [screening.STATUS_PENDING], (
            "a pending request was closed out"
        )


async def test_a_flagged_verdict_blocks_publicly_funded_assignment(
    tenant_a: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caregiver_id = await _caregiver(tenant_a, "Ada Excluded Person")
    adapter = LoopbackScreeningAdapter()
    monkeypatch.setattr(screening, "get_screening_adapter", lambda: adapter)

    await _order_and_poll(tenant_a, caregiver_id, adapter)
    run = await screening.poll_outstanding(tenant_a.agency_id)

    assert run.flagged == [str(caregiver_id)]
    async with tenant_session(tenant_a.agency_id) as session:
        caregiver = await session.get(Caregiver, caregiver_id)
        assert caregiver is not None
        assert caregiver.exclusion_check_status is ExclusionCheckStatus.flagged
        assert not caregiver.is_exclusion_cleared


async def test_a_vendor_error_while_polling_leaves_the_request_outstanding(
    tenant_a: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreachable vendor must not resolve anything, in either direction."""
    caregiver_id = await _caregiver(tenant_a, "Ada Newhire")
    adapter = LoopbackScreeningAdapter(complete_immediately=False)
    monkeypatch.setattr(screening, "get_screening_adapter", lambda: adapter)
    await _order_and_poll(tenant_a, caregiver_id, adapter)

    async def explode(vendor_request_id: str) -> ScreeningResult:
        raise ScreeningError("vendor timeout")

    monkeypatch.setattr(adapter, "fetch", explode)
    run = await screening.poll_outstanding(tenant_a.agency_id)

    assert run.failed == 1
    assert run.resolved == 0
    async with tenant_session(tenant_a.agency_id) as session:
        caregiver = await session.get(Caregiver, caregiver_id)
        assert caregiver is not None
        assert caregiver.exclusion_check_status is ExclusionCheckStatus.not_run


async def test_a_duplicate_final_result_does_not_announce_twice(
    tenant_a: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Vendors retry callbacks. A redelivery must not produce a second webhook."""
    caregiver_id = await _caregiver(tenant_a, "Ada Newhire")
    adapter = LoopbackScreeningAdapter()
    monkeypatch.setattr(screening, "get_screening_adapter", lambda: adapter)
    await _order_and_poll(tenant_a, caregiver_id, adapter)

    await screening.poll_outstanding(tenant_a.agency_id)
    async with tenant_session(tenant_a.agency_id) as session:
        request = (
            (
                await session.execute(
                    select(ScreeningRequest).where(ScreeningRequest.caregiver_id == caregiver_id)
                )
            )
            .scalars()
            .one()
        )
        result = await adapter.fetch(str(request.vendor_request_id))
        # Replaying the same final result is a no-op, not a second completion.
        assert await screening.record_result(session, request=request, result=result) is None


# --- The flagged-while-scheduled exception -----------------------------------------------


async def _assigned_future_visit(tenant: TenantFixture, caregiver_id: uuid.UUID) -> None:
    from careos.core.crypto import encrypt_field
    from careos.modules.scheduling.models import CarePlan, Client, ScheduledVisit, VisitStatus

    async with tenant_session(tenant.agency_id) as session:
        care_client = Client(
            agency_id=tenant.agency_id,
            legal_name="Held Client",
            dob_encrypted=encrypt_field("1940-01-01"),
            address_encrypted=encrypt_field("1 Somewhere St"),
            service_state="NY",
            primary_payer_type="medicaid_waiver",
        )
        session.add(care_client)
        await session.flush()
        plan = CarePlan(
            agency_id=tenant.agency_id,
            client_id=care_client.id,
            authorized_tasks=[],
            visit_frequency_rule={"rrule": "FREQ=DAILY;COUNT=1"},
            effective_start=datetime.now(UTC).date(),
        )
        session.add(plan)
        await session.flush()
        start = datetime.now(UTC) + timedelta(days=2)
        session.add(
            ScheduledVisit(
                agency_id=tenant.agency_id,
                care_plan_id=plan.id,
                caregiver_id=caregiver_id,
                scheduled_start=start,
                scheduled_end=start + timedelta(hours=2),
                status=VisitStatus.assigned,
            )
        )


async def test_flagging_someone_with_future_visits_raises_a_critical_exception(
    tenant_a: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scheduling problem is the point, not the record update.

    An excluded caregiver holding future visits means clients who will have nobody arriving
    once those visits are reassigned. That has to reach a human today.
    """
    caregiver_id = await _caregiver(tenant_a, "Working Excluded Person")
    await _assigned_future_visit(tenant_a, caregiver_id)
    adapter = LoopbackScreeningAdapter()
    monkeypatch.setattr(screening, "get_screening_adapter", lambda: adapter)

    await _order_and_poll(tenant_a, caregiver_id, adapter)
    await screening.poll_outstanding(tenant_a.agency_id)

    async with tenant_session(tenant_a.agency_id) as session:
        exceptions = (
            (
                await session.execute(
                    select(ComplianceException).where(
                        ComplianceException.rule_key == screening.FLAGGED_WHILE_SCHEDULED_RULE
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(exceptions) == 1
    assert exceptions[0].severity == "critical"
    assert exceptions[0].entity_id == caregiver_id
    assert exceptions[0].details["future_visits_assigned"] == 1


async def test_flagging_someone_with_no_future_visits_raises_no_exception(
    tenant_a: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected applicant is not a scheduling emergency; the queue must not fill with them."""
    caregiver_id = await _caregiver(tenant_a, "Applicant Excluded Person")
    adapter = LoopbackScreeningAdapter()
    monkeypatch.setattr(screening, "get_screening_adapter", lambda: adapter)

    await _order_and_poll(tenant_a, caregiver_id, adapter)
    await screening.poll_outstanding(tenant_a.agency_id)

    async with tenant_session(tenant_a.agency_id) as session:
        count = len(
            (
                await session.execute(
                    select(ComplianceException).where(
                        ComplianceException.rule_key == screening.FLAGGED_WHILE_SCHEDULED_RULE
                    )
                )
            )
            .scalars()
            .all()
        )
    assert count == 0


async def test_the_flagged_caregiver_keeps_their_visits(
    tenant_a: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silently emptying the schedule would leave clients with nobody arriving and no notice."""
    from careos.modules.scheduling.models import ScheduledVisit

    caregiver_id = await _caregiver(tenant_a, "Working Excluded Person")
    await _assigned_future_visit(tenant_a, caregiver_id)
    adapter = LoopbackScreeningAdapter()
    monkeypatch.setattr(screening, "get_screening_adapter", lambda: adapter)

    await _order_and_poll(tenant_a, caregiver_id, adapter)
    await screening.poll_outstanding(tenant_a.agency_id)

    async with tenant_session(tenant_a.agency_id) as session:
        still_assigned = (
            (
                await session.execute(
                    select(ScheduledVisit).where(ScheduledVisit.caregiver_id == caregiver_id)
                )
            )
            .scalars()
            .all()
        )
    assert len(still_assigned) == 1


# --- Re-screening ------------------------------------------------------------------------


async def test_a_stale_clearance_is_rescreened(
    tenant_a: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OIG republishes LEIE monthly. A six-month-old clearance describes a replaced list."""
    caregiver_id = await _caregiver(tenant_a, "Long Serving Aide")
    adapter = LoopbackScreeningAdapter(complete_immediately=False)
    monkeypatch.setattr(screening, "get_screening_adapter", lambda: adapter)

    async with tenant_session(tenant_a.agency_id) as session:
        caregiver = await session.get(Caregiver, caregiver_id)
        assert caregiver is not None
        caregiver.exclusion_check_status = ExclusionCheckStatus.cleared
        caregiver.exclusion_checked_at = datetime.now(UTC) - timedelta(days=200)

    run = await screening.order_due_rescreens(tenant_a.agency_id)
    assert run.ordered == 1
    assert adapter.orders[0]["checks"] == [ScreeningCheck.exclusion_list.value], (
        "a full background bundle was re-ordered when only the exclusion check recurs"
    )


async def test_a_fresh_clearance_is_not_rescreened(
    tenant_a: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caregiver_id = await _caregiver(tenant_a, "Recently Checked Aide")
    adapter = LoopbackScreeningAdapter()
    monkeypatch.setattr(screening, "get_screening_adapter", lambda: adapter)

    async with tenant_session(tenant_a.agency_id) as session:
        caregiver = await session.get(Caregiver, caregiver_id)
        assert caregiver is not None
        caregiver.exclusion_check_status = ExclusionCheckStatus.cleared
        caregiver.exclusion_checked_at = datetime.now(UTC) - timedelta(days=1)

    run = await screening.order_due_rescreens(tenant_a.agency_id)
    assert run.ordered == 0
    assert adapter.orders == []


async def test_rescreening_does_not_reset_a_caregiver_to_unassignable(
    tenant_a: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Someone mid-re-screen keeps working. Otherwise the monthly job benches the workforce."""
    caregiver_id = await _caregiver(tenant_a, "Long Serving Aide")
    adapter = LoopbackScreeningAdapter(complete_immediately=False)
    monkeypatch.setattr(screening, "get_screening_adapter", lambda: adapter)

    async with tenant_session(tenant_a.agency_id) as session:
        caregiver = await session.get(Caregiver, caregiver_id)
        assert caregiver is not None
        caregiver.exclusion_check_status = ExclusionCheckStatus.cleared
        caregiver.exclusion_checked_at = datetime.now(UTC) - timedelta(days=200)

    await screening.order_due_rescreens(tenant_a.agency_id)
    await screening.poll_outstanding(tenant_a.agency_id)

    async with tenant_session(tenant_a.agency_id) as session:
        caregiver = await session.get(Caregiver, caregiver_id)
        assert caregiver is not None
        assert caregiver.exclusion_check_status is ExclusionCheckStatus.cleared


# --- Evidence ----------------------------------------------------------------------------


async def test_ordering_and_completing_are_separately_audited(
    tenant_a: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An auditor has to tell a vendor verdict from an administrator typing one in."""
    caregiver_id = await _caregiver(tenant_a, "Ada Newhire")
    adapter = LoopbackScreeningAdapter()
    monkeypatch.setattr(screening, "get_screening_adapter", lambda: adapter)
    await _order_and_poll(tenant_a, caregiver_id, adapter)

    async with tenant_session(tenant_a.agency_id) as session:
        request = (
            (
                await session.execute(
                    select(ScreeningRequest).where(ScreeningRequest.caregiver_id == caregiver_id)
                )
            )
            .scalars()
            .one()
        )
        result = await adapter.fetch(str(request.vendor_request_id))
        await screening.record_result(
            session, request=request, result=result, principal=tenant_a.principal()
        )

    async with tenant_session(tenant_a.agency_id) as session:
        actions = [
            row.action
            for row in (
                (await session.execute(select(AuditLog).where(AuditLog.entity_id == caregiver_id)))
                .scalars()
                .all()
            )
        ]
    assert "caregiver.screening_ordered" in actions
    assert "caregiver.screening_completed" in actions


async def test_a_completed_screening_announces_the_webhook_that_had_no_producer(
    tenant_a: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`background_check.completed` was in the published contract with nothing behind it."""
    from careos.modules.webhooks.models import SubscriptionStatus, WebhookEvent, WebhookSubscription

    async with tenant_session(tenant_a.agency_id) as session:
        session.add(
            WebhookSubscription(
                agency_id=tenant_a.agency_id,
                url="https://receiver.example.com/hook",
                events=[WebhookEvent.background_check_completed.value],
                signing_secret="whsec-test-only",
                status=SubscriptionStatus.active,
            )
        )

    caregiver_id = await _caregiver(tenant_a, "Ada Newhire")
    adapter = LoopbackScreeningAdapter()
    monkeypatch.setattr(screening, "get_screening_adapter", lambda: adapter)
    await _order_and_poll(tenant_a, caregiver_id, adapter)
    await screening.poll_outstanding(tenant_a.agency_id)

    async with tenant_session(tenant_a.agency_id) as session:
        deliveries = (
            (
                await session.execute(
                    select(WebhookDelivery).where(
                        WebhookDelivery.event == WebhookEvent.background_check_completed.value
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(deliveries) == 1
    body = deliveries[0].payload
    assert body["verdict"] == "clear"
    # Match detail stays in the agency's adjudication screen, not in a third party's inbox.
    assert "matches" not in body


# --- Tenant isolation --------------------------------------------------------------------


async def test_polling_one_agency_does_not_resolve_anothers_requests(
    tenant_a: TenantFixture, tenant_b: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = LoopbackScreeningAdapter()
    monkeypatch.setattr(screening, "get_screening_adapter", lambda: adapter)
    a_caregiver = await _caregiver(tenant_a, "A Side Aide")
    b_caregiver = await _caregiver(tenant_b, "B Side Aide")
    await _order_and_poll(tenant_a, a_caregiver, adapter)
    await _order_and_poll(tenant_b, b_caregiver, adapter)

    await screening.poll_outstanding(tenant_a.agency_id)

    async with tenant_session(tenant_b.agency_id) as session:
        untouched = await session.get(Caregiver, b_caregiver)
        assert untouched is not None
        assert untouched.exclusion_check_status is ExclusionCheckStatus.not_run


# --- Through the API ---------------------------------------------------------------------


async def test_the_endpoint_returns_202_and_is_owner_admin_only(
    client, tenant_a: TenantFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caregiver_id = await _caregiver(tenant_a, "Ada Newhire")
    monkeypatch.setattr(
        "careos.modules.credentialing.screening.get_screening_adapter",
        lambda: LoopbackScreeningAdapter(complete_immediately=False),
    )

    accepted = await client.post(
        f"/v1/caregivers/{caregiver_id}/screenings",
        json={"checks": []},
        headers={**tenant_a.headers(Role.owner_admin), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["status"] == screening.STATUS_PENDING

    for role in (Role.scheduler, Role.caregiver, Role.billing_rcm):
        refused = await client.post(
            f"/v1/caregivers/{caregiver_id}/screenings",
            json={"checks": []},
            headers={**tenant_a.headers(role), "Idempotency-Key": str(uuid.uuid4())},
        )
        assert refused.status_code == 403, f"{role} could order a background check"


async def test_screening_history_is_closed_to_schedulers(client, tenant_a: TenantFixture) -> None:
    """Match detail is criminal-history material for the employment decision-maker only."""
    caregiver_id = await _caregiver(tenant_a, "Ada Newhire")
    allowed = await client.get(
        f"/v1/caregivers/{caregiver_id}/screenings",
        headers=tenant_a.headers(Role.owner_admin),
    )
    assert allowed.status_code == 200

    refused = await client.get(
        f"/v1/caregivers/{caregiver_id}/screenings",
        headers=tenant_a.headers(Role.scheduler),
    )
    assert refused.status_code == 403
