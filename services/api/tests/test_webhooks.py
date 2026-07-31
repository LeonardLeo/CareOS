"""Outbound webhooks (`05_API_Specification.md` Section 7).

A webhook is the only thing in this system that pushes data out to an address a customer typed
into a form. Three properties follow from that, and they are what these tests are mostly about.

**Payloads carry no PHI.** Section 7's own payload summaries are identifiers and statuses.
That is treated as the contract rather than as brevity, because the destination is a system
CareOS has no BAA with, reached over the public internet, chosen by a form field.

**Announcing is part of the transaction that caused it.** A rolled-back change must not have
told anybody it happened — the same reasoning that puts the audit row in the caller's
transaction, and the same failure the commit-boundary fix removed from the write path.

**The URL is attacker-influenced.** An unrestricted webhook is a request forwarder pointed at
whatever the agency likes, including the cloud metadata endpoint.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from careos.config import get_settings
from careos.db.session import begin_tenant_session, tenant_session
from careos.modules.agency.models import Role
from careos.modules.webhooks import service
from careos.modules.webhooks.models import (
    DeliveryStatus,
    SubscriptionStatus,
    WebhookDelivery,
    WebhookEvent,
    WebhookSubscription,
)
from tests.conftest import TenantFixture


async def _subscribe(client, tenant: TenantFixture, events: list[str] | None = None) -> dict:
    response = await client.post(
        "/v1/webhooks",
        headers=tenant.headers(Role.owner_admin),
        json={
            "url": "https://receiver.example.com/careos",
            "events": events or [WebhookEvent.evv_transmission_acknowledged.value],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- No PHI leaves the building -------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"legal_name": "Ada Whitfield"},
        {"client": {"address": "412 Ashbury Lane"}},
        {"caregivers": [{"id": "x", "email": "nurse@example.com"}]},
        {"visit": {"geo": {"lat": 43.1, "lng": -77.6}}},
        {"dob": "1948-03-11"},
    ],
)
def test_a_payload_containing_phi_is_refused(payload: dict) -> None:
    """Checked at every depth, and on the field name rather than the value.

    A value-based check cannot tell a person's name from any other string, so it would only
    catch what it happened to recognise — which is not a boundary, it is a filter with gaps.
    """
    with pytest.raises(service.WebhookPayloadError):
        service.assert_payload_carries_no_phi(payload)


def test_an_identifier_only_payload_is_accepted() -> None:
    """The shape Section 7 actually describes."""
    service.assert_payload_carries_no_phi(
        {
            "evv_record_id": str(uuid.uuid4()),
            "scheduled_visit_id": str(uuid.uuid4()),
            "transmission_status": "acknowledged",
            "attempts": 1,
            "occurred_at": datetime.now(UTC).isoformat(),
        }
    )


async def test_the_evv_worker_announces_without_naming_anyone(
    client, tenant_a: TenantFixture
) -> None:
    """The producer that actually exists today, checked end to end.

    The guard above proves the rule is enforced; this proves the one caller obeys it, which is
    a different claim. A payload assembled from a visit is exactly where a caregiver's name
    would end up by accident.
    """
    from careos.modules.scheduling.models import EVVRecord, TransmissionStatus
    from careos.workers.evv_transmission import _announce

    await _subscribe(client, tenant_a)

    async with tenant_session(tenant_a.agency_id) as session:
        record = EVVRecord(
            agency_id=tenant_a.agency_id,
            scheduled_visit_id=uuid.uuid4(),
            transmission_attempts=1,
            transmission_status=TransmissionStatus.acknowledged,
        )
        # Not persisted: the payload is built from the object's fields, and what this asserts
        # is which of them are read.
        record.id = uuid.uuid4()
        await _announce(
            session,
            tenant_a.agency_id,
            record,
            WebhookEvent.evv_transmission_acknowledged,
        )

    async with tenant_session(tenant_a.agency_id) as session:
        deliveries = (await session.execute(select(WebhookDelivery))).scalars().all()

    assert len(deliveries) == 1
    # Raises if the producer ever starts including a name or an address.
    service.assert_payload_carries_no_phi(deliveries[0].payload)


# --- Signing --------------------------------------------------------------------------------


def test_a_signature_verifies_and_a_tampered_body_does_not() -> None:
    secret = service.generate_signing_secret()
    body = service.canonical_body({"event": "x", "id": "1"})
    header = service.sign(body, secret)

    assert service.verify(header, body, secret)
    assert not service.verify(header, body + b" ", secret)
    assert not service.verify(header, body, secret + "x")


def test_an_old_signature_is_rejected() -> None:
    """The timestamp is inside the signed material, which is what makes replay bounded.

    Signing the body alone would leave a captured delivery valid forever. This asserts the
    receiver-side check an integrator is told to implement, using the same code they would.
    """
    secret = service.generate_signing_secret()
    body = service.canonical_body({"id": "1"})
    stale = int((datetime.now(UTC) - timedelta(hours=2)).timestamp())
    header = service.sign(body, secret, timestamp=stale)

    assert not service.verify(header, body, secret)
    # ...and it is the age that rejected it, not the digest.
    assert service.verify(header, body, secret, tolerance=60 * 60 * 24)


def test_a_signature_cannot_be_forged_by_moving_the_timestamp() -> None:
    """Re-stamping a captured delivery must not produce a valid signature."""
    secret = service.generate_signing_secret()
    body = service.canonical_body({"id": "1"})
    original = service.sign(body, secret, timestamp=1_000_000)
    digest = original.split("v1=")[1]

    now = int(datetime.now(UTC).timestamp())
    assert not service.verify(f"t={now},v1={digest}", body, secret)


# --- Subscription management ----------------------------------------------------------------


async def test_the_signing_secret_is_returned_once_and_never_again(
    client, tenant_a: TenantFixture
) -> None:
    """A secret a list endpoint hands back leaks through every cached copy of that response."""
    created = await _subscribe(client, tenant_a)
    assert created["signing_secret"].startswith("whsec_")

    listed = await client.get("/v1/webhooks", headers=tenant_a.headers(Role.owner_admin))
    assert listed.status_code == 200
    assert "signing_secret" not in listed.text
    assert "whsec_" not in listed.text


async def test_an_unknown_event_name_is_refused(client, tenant_a: TenantFixture) -> None:
    """Otherwise a receiver subscribes to a typo, gets a 201, and waits forever."""
    response = await client.post(
        "/v1/webhooks",
        headers=tenant_a.headers(Role.owner_admin),
        json={"url": "https://receiver.example.com/x", "events": ["evv.acknowledged"]},
    )
    assert response.status_code == 422
    assert "evv.acknowledged" in response.text
    # The error names the real ones, so the fix does not require reading the spec.
    assert "evv.transmission_acknowledged" in response.text


@pytest.mark.parametrize("role", [Role.scheduler, Role.clinical_supervisor, Role.caregiver])
async def test_only_an_owner_admin_can_subscribe(
    client, tenant_a: TenantFixture, role: Role
) -> None:
    """Where an agency's event stream is sent is a security setting, not a preference."""
    response = await client.post(
        "/v1/webhooks",
        headers=tenant_a.headers(role),
        json={"url": "https://receiver.example.com/x", "events": ["claim.status_changed"]},
    )
    assert response.status_code == 403


async def test_subscriptions_do_not_cross_tenants(
    client, tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    await _subscribe(client, tenant_a)
    listed = await client.get("/v1/webhooks", headers=tenant_b.headers(Role.owner_admin))
    assert listed.status_code == 200
    assert listed.json() == []


async def test_reactivating_clears_the_failure_count(client, tenant_a: TenantFixture) -> None:
    """Without this a fixed endpoint is disabled again on its very next failure.

    The counter would still be sitting at the threshold, so one more blip re-trips it — and
    the agency would reasonably conclude that re-enabling does not work.
    """
    created = await _subscribe(client, tenant_a)

    async with tenant_session(tenant_a.agency_id) as session:
        subscription = await session.get(WebhookSubscription, uuid.UUID(created["id"]))
        assert subscription is not None
        subscription.status = SubscriptionStatus.disabled
        subscription.consecutive_failures = service.FAILURES_BEFORE_DISABLE
        subscription.disabled_reason = "20 consecutive delivery failures."

    response = await client.patch(
        f"/v1/webhooks/{created['id']}",
        headers=tenant_a.headers(Role.owner_admin),
        json={"status": "active"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"
    assert body["consecutive_failures"] == 0
    assert body["disabled_reason"] is None


async def test_a_subscription_cannot_be_set_to_disabled_by_hand(
    client, tenant_a: TenantFixture
) -> None:
    """`disabled` means "the system turned this off", and it carries a reason.

    Letting a caller set it directly would produce a disabled subscription with no explanation,
    which is the state the reason field exists to prevent.
    """
    created = await _subscribe(client, tenant_a)
    response = await client.patch(
        f"/v1/webhooks/{created['id']}",
        headers=tenant_a.headers(Role.owner_admin),
        json={"status": "disabled"},
    )
    assert response.status_code == 422


# --- The URL is attacker-influenced ---------------------------------------------------------


def test_production_refuses_a_private_or_loopback_url(monkeypatch) -> None:
    """An unrestricted webhook is a request forwarder with CareOS's network position.

    `http://169.254.169.254/` is the cloud metadata endpoint; an internal admin service is the
    other obvious target. Checked in production only, because a local integration has nowhere
    else to point.
    """
    from careos.core.errors import ValidationError

    for key, value in {
        "CAREOS_ENVIRONMENT": "production",
        "CAREOS_JWT_SECRET": "a-real-production-secret-value",
        "CAREOS_EVV_USE_SANDBOX": "false",
        "CAREOS_CORS_ALLOWED_ORIGINS": '["https://app.careos.example"]',
        "CAREOS_RATE_LIMIT_BACKEND": "redis",
        "CAREOS_METRICS_TOKEN": "set-in-the-secrets-manager",
        "CAREOS_MFA_REQUIRED": "true",
        "CAREOS_SCREENING_ADAPTER": "vendor",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        assert get_settings().is_production
        with pytest.raises(ValidationError, match="private or loopback"):
            service.validate_subscription_url("https://localhost/hook")
        with pytest.raises(ValidationError, match="private or loopback"):
            service.validate_subscription_url("https://169.254.169.254/latest/meta-data/")
        # And plain http is refused outright in production.
        with pytest.raises(ValidationError, match="https"):
            service.validate_subscription_url("http://receiver.example.com/hook")
        # A public https URL is fine.
        assert service.validate_subscription_url("https://receiver.example.com/hook")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_the_delivery_time_check_exists_separately_from_the_subscription_time_one() -> None:
    """DNS is not a promise.

    A hostname that resolved publicly when the subscription was created can resolve to
    169.254.169.254 by the time the worker connects, so the check immediately before the
    connection is the one that actually prevents the request.
    """
    import inspect

    from careos.workers import webhook_delivery

    source = inspect.getsource(webhook_delivery._deliver_one)
    assert "is_forbidden_target" in source, (
        "the worker must re-check the target at delivery time, not trust subscription time"
    )
    assert "follow_redirects=False" in inspect.getsource(webhook_delivery.drain_agency), (
        "following a redirect turns a validated URL back into an unvalidated one"
    )


# --- Delivery -------------------------------------------------------------------------------


async def test_only_subscribed_events_are_queued(client, tenant_a: TenantFixture) -> None:
    """An empty or narrow event list means narrow, not everything."""
    await _subscribe(client, tenant_a, events=[WebhookEvent.claim_status_changed.value])

    async with tenant_session(tenant_a.agency_id) as session:
        await service.enqueue(
            session,
            agency_id=tenant_a.agency_id,
            event=WebhookEvent.evv_transmission_rejected,
            payload={"evv_record_id": str(uuid.uuid4())},
        )

    async with tenant_session(tenant_a.agency_id) as session:
        assert (await session.execute(select(WebhookDelivery))).scalars().all() == []


async def test_a_rolled_back_change_announces_nothing(client, tenant_a: TenantFixture) -> None:
    """The transactional outbox, which is the whole reason enqueue takes a session.

    Calling the receiver inline would announce something that then rolled back, and no
    retraction is possible once it has been sent.
    """
    await _subscribe(client, tenant_a)

    class Rollback(RuntimeError):
        pass

    with pytest.raises(Rollback):
        async with tenant_session(tenant_a.agency_id) as session:
            await service.enqueue(
                session,
                agency_id=tenant_a.agency_id,
                event=WebhookEvent.evv_transmission_acknowledged,
                payload={"evv_record_id": str(uuid.uuid4())},
            )
            raise Rollback

    async with tenant_session(tenant_a.agency_id) as session:
        assert (await session.execute(select(WebhookDelivery))).scalars().all() == []


async def test_a_failing_receiver_retries_then_gives_up_and_disables(
    client, tenant_a: TenantFixture
) -> None:
    """Backoff, abandonment, and disablement, against a receiver that is simply not there.

    The URL points at a closed port, so every attempt fails for real rather than through a
    patched transport — the retry path is the one thing here that must work when nothing else
    does.
    """
    from careos.workers import webhook_delivery

    created = await _subscribe(client, tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        subscription = await session.get(WebhookSubscription, uuid.UUID(created["id"]))
        assert subscription is not None
        subscription.url = "http://127.0.0.1:1/hook"

    async with tenant_session(tenant_a.agency_id) as session:
        await service.enqueue(
            session,
            agency_id=tenant_a.agency_id,
            event=WebhookEvent.evv_transmission_acknowledged,
            payload={"evv_record_id": str(uuid.uuid4())},
        )

    # Each pass makes one attempt; the backoff is cleared between passes so the test does not
    # sit out the real six-hour wait.
    for _ in range(service.MAX_ATTEMPTS):
        await webhook_delivery.drain_agency(tenant_a.agency_id)
        async with tenant_session(tenant_a.agency_id) as session:
            for delivery in (await session.execute(select(WebhookDelivery))).scalars().all():
                if delivery.status is DeliveryStatus.failing:
                    delivery.next_attempt_at = datetime.now(UTC)

    async with tenant_session(tenant_a.agency_id) as session:
        delivery = (await session.execute(select(WebhookDelivery))).scalars().one()
        assert delivery.status is DeliveryStatus.abandoned
        assert delivery.attempts == service.MAX_ATTEMPTS
        assert delivery.last_error
        # Kept, not deleted: "did you try" has to stay answerable.
        assert delivery.payload


async def test_a_paused_subscription_stops_receiving(client, tenant_a: TenantFixture) -> None:
    """Queued-then-paused must not deliver. The agency has said they do not want these."""
    from careos.workers import webhook_delivery

    created = await _subscribe(client, tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        await service.enqueue(
            session,
            agency_id=tenant_a.agency_id,
            event=WebhookEvent.evv_transmission_acknowledged,
            payload={"evv_record_id": str(uuid.uuid4())},
        )

    paused = await client.patch(
        f"/v1/webhooks/{created['id']}",
        headers=tenant_a.headers(Role.owner_admin),
        json={"status": "paused"},
    )
    assert paused.status_code == 200

    run = await webhook_delivery.drain_agency(tenant_a.agency_id)
    assert run.attempted == 0
    assert run.abandoned == 1


async def test_deliveries_are_visible_to_the_agency(client, tenant_a: TenantFixture) -> None:
    """ "Did you send it?" is the first question of every webhook integration."""
    created = await _subscribe(client, tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        await service.enqueue(
            session,
            agency_id=tenant_a.agency_id,
            event=WebhookEvent.evv_transmission_acknowledged,
            payload={"evv_record_id": str(uuid.uuid4())},
        )

    response = await client.get(
        f"/v1/webhooks/{created['id']}/deliveries",
        headers=tenant_a.headers(Role.owner_admin),
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["event"] == WebhookEvent.evv_transmission_acknowledged.value
    assert body[0]["status"] == DeliveryStatus.pending.value


# --- The calendar-driven producer -----------------------------------------------------------


async def _credential_expiring_in(tenant: TenantFixture, days: int) -> uuid.UUID:
    from careos.modules.credentialing.models import Credential, VerificationStatus

    async with tenant_session(tenant.agency_id) as session:
        credential = Credential(
            agency_id=tenant.agency_id,
            caregiver_id=tenant.caregiver_id,
            credential_type="HHA",
            verification_status=VerificationStatus.verified,
            expiration_date=datetime.now(UTC).date() + timedelta(days=days),
        )
        session.add(credential)
        await session.flush()
        return credential.id


async def test_expiring_credential_is_announced_once_not_daily(
    client, tenant_a: TenantFixture, reference_data: None
) -> None:
    """The defect this producer exists to avoid.

    "Expires in 12 days" is true again tomorrow. A daily job without deduplication re-sends
    the same notice every day until the credential expires, which trains the receiver to
    ignore the event and is indistinguishable from a retry storm.
    """
    from careos.workers import credential_expiry

    await _subscribe(client, tenant_a, events=[WebhookEvent.credential_expiring_soon.value])
    credential_id = await _credential_expiring_in(tenant_a, days=12)

    first = await credential_expiry.announce_expiring_credentials(tenant_a.agency_id)
    assert first.queued == 1

    # A day later. Same credential, same horizon, one day fewer — not a new event.
    second = await credential_expiry.announce_expiring_credentials(
        tenant_a.agency_id, as_of=datetime.now(UTC).date() + timedelta(days=1)
    )
    assert second.considered == 1, "the credential is still expiring; it must still be seen"
    assert second.queued == 0

    async with tenant_session(tenant_a.agency_id) as session:
        deliveries = (await session.execute(select(WebhookDelivery))).scalars().all()
    assert len(deliveries) == 1
    assert deliveries[0].payload["credential_id"] == str(credential_id)


async def test_crossing_into_a_tighter_horizon_is_a_new_event(
    client, tenant_a: TenantFixture, reference_data: None
) -> None:
    """Otherwise 60/30/7 would be one reminder wearing three hats."""
    from careos.workers import credential_expiry

    await _subscribe(client, tenant_a, events=[WebhookEvent.credential_expiring_soon.value])
    await _credential_expiring_in(tenant_a, days=45)

    await credential_expiry.announce_expiring_credentials(tenant_a.agency_id)
    # 20 days later the same credential is inside the 30-day window.
    later = await credential_expiry.announce_expiring_credentials(
        tenant_a.agency_id, as_of=datetime.now(UTC).date() + timedelta(days=20)
    )
    assert later.queued == 1

    async with tenant_session(tenant_a.agency_id) as session:
        buckets = sorted(
            d.payload["bucket"] for d in (await session.execute(select(WebhookDelivery))).scalars()
        )
    assert buckets == [30, 60]


async def test_credential_notice_carries_no_caregiver_name(
    client, tenant_a: TenantFixture, reference_data: None
) -> None:
    """The dashboard query hands over `caregiver_name`; the payload must not carry it.

    Worth its own test because the temptation is real — the name is right there in
    `ExpiringCredential`, and including it would make the receiver's email nicer. It would
    also put a caregiver's legal name on an unauthenticated push to a URL from a form field.
    """
    from careos.workers import credential_expiry

    await _subscribe(client, tenant_a, events=[WebhookEvent.credential_expiring_soon.value])
    await _credential_expiring_in(tenant_a, days=5)
    await credential_expiry.announce_expiring_credentials(tenant_a.agency_id)

    async with tenant_session(tenant_a.agency_id) as session:
        delivery = (await session.execute(select(WebhookDelivery))).scalars().one()

    assert set(delivery.payload) == {
        "credential_id",
        "caregiver_id",
        "credential_type",
        "expiration_date",
        "days_until_expiry",
        "bucket",
        "already_expired",
    }
    serialized = service.canonical_body(delivery.payload).decode()
    assert tenant_a.caregiver.legal_name not in serialized


async def test_dedupe_is_per_subscription(
    client, tenant_a: TenantFixture, reference_data: None
) -> None:
    """A subscription added after the first run still gets the notice.

    Deduplication is about not repeating *to a receiver*, not about the event having been
    announced somewhere. Keying it per subscription is what keeps a second integration from
    silently receiving nothing.
    """
    from careos.workers import credential_expiry

    await _subscribe(client, tenant_a, events=[WebhookEvent.credential_expiring_soon.value])
    await _credential_expiring_in(tenant_a, days=5)
    await credential_expiry.announce_expiring_credentials(tenant_a.agency_id)

    second_receiver = await client.post(
        "/v1/webhooks",
        headers=tenant_a.headers(Role.owner_admin),
        json={
            "url": "https://second-receiver.example.com/careos",
            "events": [WebhookEvent.credential_expiring_soon.value],
        },
    )
    assert second_receiver.status_code == 201

    again = await credential_expiry.announce_expiring_credentials(tenant_a.agency_id)
    assert again.queued == 1

    async with tenant_session(tenant_a.agency_id) as session:
        subscriptions = {
            d.subscription_id for d in (await session.execute(select(WebhookDelivery))).scalars()
        }
    assert len(subscriptions) == 2


async def test_a_delivery_another_worker_holds_is_skipped_not_resent(
    client, tenant_a: TenantFixture
) -> None:
    """Two workers draining one agency must not both send the same delivery.

    Receivers are asked to deduplicate on `CareOS-Delivery`, but at-least-once is a concession
    to the network, not a reason to send twice on purpose. Simulated by holding the row lock in
    one transaction — which is exactly what a concurrent worker mid-delivery is doing — and
    asserting the drain skips rather than picks it up.
    """
    from careos.workers import webhook_delivery

    await _subscribe(client, tenant_a)
    async with tenant_session(tenant_a.agency_id) as session:
        await service.enqueue(
            session,
            agency_id=tenant_a.agency_id,
            event=WebhookEvent.evv_transmission_acknowledged,
            payload={"evv_record_id": str(uuid.uuid4())},
        )

    holder = await begin_tenant_session(tenant_a.agency_id)
    try:
        locked = await holder.execute(
            select(WebhookDelivery).with_for_update(skip_locked=True).limit(1)
        )
        assert locked.scalars().first() is not None, "nothing to lock; the test proves nothing"

        # Bounded, because the failure mode without `SKIP LOCKED` is not a wrong answer but no
        # answer: the drain selects the row anyway and then blocks forever on the UPDATE,
        # waiting for a lock the holder never releases. Confirmed by removing the clause and
        # watching this hang. A test that hangs is a CI job that times out with nothing to
        # read, so the wait is capped and reported as what it is.
        try:
            run = await asyncio.wait_for(webhook_delivery.drain_agency(tenant_a.agency_id), 15)
        except TimeoutError:
            pytest.fail(
                "drain_agency blocked on a delivery another worker holds. It must select "
                "FOR UPDATE SKIP LOCKED and move on, not queue behind the lock."
            )
        assert run.attempted == 0
    finally:
        await holder.rollback()
        await holder.close()
