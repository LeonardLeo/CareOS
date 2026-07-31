"""Delivering queued webhooks.

The other half of the transactional outbox in `careos.modules.webhooks.service`. Everything
here runs outside a request, which is the point: an agency's slow or unreachable endpoint costs
this worker time, not a caregiver's clock-in.

Shaped like `evv_transmission.py` — drain a bounded batch per agency, back off on failure,
give up loudly rather than retrying forever — because an operator who has learned one of these
should not have to learn the other.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core import metrics
from careos.db.session import tenant_session
from careos.modules.webhooks import service
from careos.modules.webhooks.models import (
    DeliveryStatus,
    SubscriptionStatus,
    WebhookDelivery,
    WebhookSubscription,
)

logger = structlog.get_logger(__name__)

#: A receiver gets this long to answer. Short on purpose: a webhook is a notification, and a
#: receiver that needs ten seconds to acknowledge one should be queueing it themselves.
DELIVERY_TIMEOUT_SECONDS = 10.0


@dataclass
class DeliveryRun:
    attempted: int = 0
    delivered: int = 0
    retrying: int = 0
    abandoned: int = 0
    subscriptions_disabled: int = 0


async def _select_due(session: AsyncSession, limit: int) -> list[WebhookDelivery]:
    now = datetime.now(UTC)
    result = await session.execute(
        select(WebhookDelivery)
        .where(
            WebhookDelivery.status.in_([DeliveryStatus.pending, DeliveryStatus.failing]),
            WebhookDelivery.next_attempt_at <= now,
        )
        .order_by(WebhookDelivery.created_at)
        .limit(limit)
        # Same lock the EVV worker takes, for the same reason: two workers draining one agency
        # would otherwise both select the same due rows and send the delivery twice. Receivers
        # are told to deduplicate on `CareOS-Delivery`, but "at least once" is a contract with
        # the network, not a licence to duplicate on purpose.
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def _deliver_one(
    client: httpx.AsyncClient,
    delivery: WebhookDelivery,
    subscription: WebhookSubscription,
) -> tuple[bool, int | None, str | None]:
    """Attempt one delivery. Returns (succeeded, status code, error)."""
    # Re-checked here, not only when the subscription was created. DNS is not a promise: a
    # name that resolved publicly then can resolve to 169.254.169.254 now, and the check that
    # matters is the one immediately before the connection.
    if service.is_forbidden_target(subscription.url):
        return False, None, "URL resolves to a private or loopback address"

    body = service.canonical_body(delivery.payload)
    headers = {
        "Content-Type": "application/json",
        service.SIGNATURE_HEADER: service.sign(body, subscription.signing_secret),
        service.EVENT_HEADER: delivery.event.value,
        # So a receiver can deduplicate. Retries reuse the id, which is what makes
        # at-least-once delivery safe for them to consume.
        service.DELIVERY_HEADER: str(delivery.id),
    }

    try:
        response = await client.post(
            subscription.url, content=body, headers=headers, timeout=DELIVERY_TIMEOUT_SECONDS
        )
    except httpx.HTTPError as exc:
        return False, None, f"{type(exc).__name__}: {exc}"

    # Any 2xx counts. Receivers legitimately answer 200, 202, or 204, and insisting on one of
    # them would fail integrations that are working.
    if 200 <= response.status_code < 300:
        return True, response.status_code, None
    return False, response.status_code, f"receiver returned {response.status_code}"


async def drain_agency(agency_id: uuid.UUID, *, limit: int = 100) -> DeliveryRun:
    """Deliver up to `limit` due webhooks for one agency.

    Tenant-scoped for the same reason the EVV worker is: the session's tenant context drives
    RLS, so a bug here cannot reach another agency's queue.
    """
    run = DeliveryRun()

    async with tenant_session(agency_id) as session:
        due = await _select_due(session, limit)
        if not due:
            return run

        subscriptions = {
            s.id: s for s in (await session.execute(select(WebhookSubscription))).scalars().all()
        }

        async with httpx.AsyncClient(follow_redirects=False) as client:
            # Redirects are not followed on purpose. A receiver that 302s to somewhere else
            # turns a validated URL into an unvalidated one, which is the SSRF check undone at
            # delivery time by the very party it constrains.
            for delivery in due:
                subscription = subscriptions.get(delivery.subscription_id)
                if subscription is None or subscription.status is not SubscriptionStatus.active:
                    # Paused or disabled between enqueue and now. Not an error and not a
                    # retry: the agency has said they do not want these.
                    delivery.status = DeliveryStatus.abandoned
                    delivery.last_error = "subscription is no longer active"
                    run.abandoned += 1
                    continue

                run.attempted += 1
                delivery.attempts += 1
                delivery.last_attempt_at = datetime.now(UTC)

                ok, status_code, error = await _deliver_one(client, delivery, subscription)
                delivery.last_response_status = status_code
                delivery.last_error = error

                if ok:
                    delivery.status = DeliveryStatus.delivered
                    delivery.next_attempt_at = None
                    subscription.consecutive_failures = 0
                    subscription.last_success_at = datetime.now(UTC)
                    run.delivered += 1
                    metrics.webhook_deliveries_total.labels(outcome="delivered").inc()
                    continue

                subscription.consecutive_failures += 1
                if delivery.attempts >= service.MAX_ATTEMPTS:
                    delivery.status = DeliveryStatus.abandoned
                    delivery.next_attempt_at = None
                    run.abandoned += 1
                    metrics.webhook_deliveries_total.labels(outcome="abandoned").inc()
                    logger.warning(
                        "webhook.abandoned",
                        delivery_id=str(delivery.id),
                        webhook_event=delivery.event.value,
                        attempts=delivery.attempts,
                        last_error=error,
                    )
                else:
                    delivery.status = DeliveryStatus.failing
                    delivery.next_attempt_at = datetime.now(UTC) + timedelta(
                        seconds=service.RETRY_BACKOFF_SECONDS[delivery.attempts]
                    )
                    run.retrying += 1
                    metrics.webhook_deliveries_total.labels(outcome="retrying").inc()

                if subscription.consecutive_failures >= service.FAILURES_BEFORE_DISABLE:
                    # Stop the queue growing against a URL that is not coming back. Recorded in
                    # words rather than a flag, because the agency has to be able to find out
                    # why their webhooks stopped without reading the code.
                    subscription.status = SubscriptionStatus.disabled
                    subscription.disabled_reason = (
                        f"{subscription.consecutive_failures} consecutive delivery failures. "
                        f"Last error: {error}. Re-enable once the endpoint is reachable."
                    )
                    run.subscriptions_disabled += 1
                    metrics.webhook_subscriptions_disabled_total.inc()
                    logger.error(
                        "webhook.subscription_disabled",
                        subscription_id=str(subscription.id),
                        consecutive_failures=subscription.consecutive_failures,
                        last_error=error,
                    )

    return run
