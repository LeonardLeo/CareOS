"""Webhook subscription management (`05_API_Specification.md` Section 7).

Owner-admin only. A subscription decides where a stream of this agency's operational events is
sent, which makes it closer to a security setting than to a preference — the same reasoning
that keeps data export off the auditor role.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.api import schemas
from careos.api.deps import db_session
from careos.core.audit import AuditAction, record_audit
from careos.core.errors import NotFoundError, ValidationError
from careos.core.rbac import requires
from careos.core.security import Principal
from careos.modules.agency.models import Role
from careos.modules.webhooks import service
from careos.modules.webhooks.models import (
    SubscriptionStatus,
    WebhookDelivery,
    WebhookEvent,
    WebhookSubscription,
)

router = APIRouter(tags=["webhooks"])


def _validate_events(events: list[str]) -> list[str]:
    """Reject an unknown event name rather than accepting a subscription that never fires.

    The failure this prevents is silent: a receiver subscribes to `evv.acknowledged`, gets a
    201, and waits forever for an event whose real name is `evv.transmission_acknowledged`.
    """
    known = {event.value for event in WebhookEvent}
    unknown = sorted(set(events) - known)
    if unknown:
        raise ValidationError(
            f"Unknown webhook event(s): {', '.join(unknown)}.",
            details={"unknown": unknown, "supported": sorted(known)},
        )
    return sorted(set(events))


@router.post("/webhooks", response_model=schemas.WebhookSubscriptionCreated, status_code=201)
async def create_subscription(
    payload: schemas.WebhookSubscriptionCreate,
    principal: Principal = Depends(requires(Role.owner_admin)),
    session: AsyncSession = Depends(db_session),
) -> schemas.WebhookSubscriptionCreated:
    """Register an endpoint to receive this agency's events.

    **The signing secret is in this response and in no other.** A receiver that loses it needs
    a new subscription. That is deliberate: a secret any list endpoint will hand back is a
    secret that leaks through every screenshot, proxy log, and cached response of that endpoint,
    and the recovery path for a lost one is cheap.
    """
    service.validate_subscription_url(payload.url)
    events = _validate_events(payload.events)

    subscription = WebhookSubscription(
        agency_id=principal.agency_id,
        url=payload.url,
        signing_secret=service.generate_signing_secret(),
        events=events,
        description=payload.description,
        status=SubscriptionStatus.active,
    )
    session.add(subscription)
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.webhook_subscription_created,
        entity_type="webhook_subscription",
        entity_id=subscription.id,
        # The URL, not the secret. An audit log is read by more people than the response was.
        after_state={"url": subscription.url, "events": events},
    )

    return schemas.WebhookSubscriptionCreated(
        id=subscription.id,
        url=subscription.url,
        events=subscription.events,
        status=subscription.status.value,
        description=subscription.description,
        disabled_reason=None,
        consecutive_failures=0,
        last_success_at=None,
        created_at=subscription.created_at,
        signing_secret=subscription.signing_secret,
    )


@router.get("/webhooks", response_model=list[schemas.WebhookSubscriptionOut])
async def list_subscriptions(
    principal: Principal = Depends(requires(Role.owner_admin, Role.auditor)),
    session: AsyncSession = Depends(db_session),
) -> list[schemas.WebhookSubscriptionOut]:
    """Every subscription for this agency. Never includes the signing secret."""
    result = await session.execute(
        select(WebhookSubscription).order_by(WebhookSubscription.created_at)
    )
    subscriptions = result.scalars().all()
    return [schemas.WebhookSubscriptionOut.model_validate(s) for s in subscriptions]


@router.patch("/webhooks/{subscription_id}", response_model=schemas.WebhookSubscriptionOut)
async def update_subscription(
    subscription_id: uuid.UUID,
    payload: schemas.WebhookSubscriptionUpdate,
    principal: Principal = Depends(requires(Role.owner_admin)),
    session: AsyncSession = Depends(db_session),
) -> schemas.WebhookSubscriptionOut:
    """Change what a subscription receives, or pause and resume it.

    Re-activating a subscription the system disabled clears its failure count and its reason.
    Without that, a fixed endpoint would be disabled again on its very next failure, since the
    counter would still be sitting at the threshold.
    """
    subscription = await session.get(WebhookSubscription, subscription_id)
    if subscription is None:
        raise NotFoundError("Webhook subscription not found")

    before = {
        "events": list(subscription.events or []),
        "status": subscription.status.value,
    }

    if payload.events is not None:
        subscription.events = _validate_events(payload.events)
    if payload.description is not None:
        subscription.description = payload.description
    if payload.status is not None:
        if payload.status not in {SubscriptionStatus.active, SubscriptionStatus.paused}:
            raise ValidationError(
                "A subscription can be set to active or paused. `disabled` is set by the "
                "system after repeated delivery failure and is cleared by re-activating.",
                details={"status": payload.status},
            )
        subscription.status = SubscriptionStatus(payload.status)
        if subscription.status is SubscriptionStatus.active:
            subscription.consecutive_failures = 0
            subscription.disabled_reason = None

    await session.flush()
    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.webhook_subscription_updated,
        entity_type="webhook_subscription",
        entity_id=subscription.id,
        before_state=before,
        after_state={"events": subscription.events, "status": subscription.status.value},
    )
    return schemas.WebhookSubscriptionOut.model_validate(subscription)


@router.get(
    "/webhooks/{subscription_id}/deliveries",
    response_model=list[schemas.WebhookDeliveryOut],
)
async def list_deliveries(
    subscription_id: uuid.UUID,
    limit: int = Query(default=50, le=200),
    principal: Principal = Depends(requires(Role.owner_admin, Role.auditor)),
    session: AsyncSession = Depends(db_session),
) -> list[schemas.WebhookDeliveryOut]:
    """Recent delivery attempts, newest first.

    The reason this endpoint exists: "did you send it?" is the first question of every webhook
    integration, and an answer that requires database access is an answer only CareOS can give.
    """
    subscription = await session.get(WebhookSubscription, subscription_id)
    if subscription is None:
        raise NotFoundError("Webhook subscription not found")

    deliveries = (
        (
            await session.execute(
                select(WebhookDelivery)
                .where(WebhookDelivery.subscription_id == subscription_id)
                .order_by(WebhookDelivery.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [schemas.WebhookDeliveryOut.model_validate(d) for d in deliveries]
