"""Outbound webhook subscriptions and their delivery record (`05_API_Specification.md` §7).

Section 7 lists four events and a one-line payload summary for each. Everything else about how
a webhook is delivered is undefined there, and the choices below are the ones that make the
difference between a feature and a liability.

**Payloads carry identifiers and status, never PHI.** Look at what §7 actually specifies:
"Caregiver ID, credential type, days until expiration" — identifiers and facts about a record,
not a person's name, address, or date of birth. That is not an accident of brevity and it is
treated here as the contract. A webhook is an unauthenticated push to a URL an agency
administrator typed into a form, crossing the public internet to a system CareOS has no BAA
with and cannot audit. Anything a receiver needs beyond an id it can fetch from the API, with a
token, over a channel that leaves an audit trail. `assert_payload_carries_no_phi` enforces this
at the point of enqueue rather than at review time.

**Delivery is a transactional outbox.** The event row is written in the same transaction as the
business change that caused it, exactly like the audit log. A worker delivers it afterwards.
The alternative — calling the receiver inline — makes an agency's slow endpoint into CareOS's
latency and an unreachable one into a failed clock-in, and it can announce something that then
rolls back. Here a rolled-back transaction takes its unsent webhook with it.

**Subscriptions can be disabled but never silently.** A receiver that has been failing for a
day is disabled to stop the retry queue growing without bound, and the reason is recorded so an
agency asking "why did the webhooks stop" has an answer.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from careos.db.base import Base, PrimaryKeyMixin, TenantMixin, TimestampMixin


class WebhookEvent(enum.StrEnum):
    """The events a subscription may ask for.

    Exactly the four in `05_API_Specification.md` Section 7 — a closed set, so a typo in a
    subscription request is a 422 rather than a subscription that silently never fires.

    Two of them have no producer yet: `background_check.completed` needs a screening vendor
    integration, and `claim.status_changed` is Phase 3. They are defined here because the
    contract is published and a receiver may reasonably subscribe in advance, and because
    leaving them out would mean changing the enum — a migration — when those land.
    """

    background_check_completed = "background_check.completed"
    evv_transmission_acknowledged = "evv.transmission_acknowledged"
    evv_transmission_rejected = "evv.transmission_rejected"
    claim_status_changed = "claim.status_changed"
    credential_expiring_soon = "credential.expiring_soon"


class SubscriptionStatus(enum.StrEnum):
    active = "active"
    #: Turned off by an administrator.
    paused = "paused"
    #: Turned off by the system after repeated delivery failure. See `disabled_reason`.
    disabled = "disabled"


class DeliveryStatus(enum.StrEnum):
    pending = "pending"
    delivered = "delivered"
    #: Retries remain; the worker will try again after the backoff.
    failing = "failing"
    #: Retries exhausted. Kept, not deleted — "we sent it" needs to be answerable either way.
    abandoned = "abandoned"


class WebhookSubscription(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "webhook_subscription"

    url: Mapped[str] = mapped_column(Text, nullable=False)

    #: Shared secret for the HMAC signature. Stored rather than hashed, because signing
    #: requires the secret itself — unlike a password, which is only ever compared. It is
    #: returned to the caller exactly once, at creation, and never again by any endpoint.
    signing_secret: Mapped[str] = mapped_column(Text, nullable=False)

    #: Which events this subscription wants. An empty list means none, not all: a subscription
    #: that silently received everything because someone forgot a field would be the wrong
    #: default for a system carrying health data.
    events: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="webhook_subscription_status"),
        nullable=False,
        default=SubscriptionStatus.active,
    )
    #: Why the system disabled it, in words an agency administrator can act on.
    disabled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_webhook_subscription_agency", "agency_id", "status"),)


class WebhookDelivery(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    """One event queued for one subscription.

    A row per (event, subscription) rather than per event: two subscribers to the same event
    fail and retry independently, and a delivery record that covered several receivers could
    not say which of them actually got it.
    """

    __tablename__ = "webhook_delivery"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("webhook_subscription.id", ondelete="CASCADE"),
        nullable=False,
    )
    event: Mapped[WebhookEvent] = mapped_column(
        # `values_callable` so the column stores `evv.transmission_acknowledged` — the name
        # `05_API_Specification.md` Section 7 publishes and a receiver subscribes to. Without
        # it SQLAlchemy persists the Python member *name*, `evv_transmission_acknowledged`,
        # which is a different string from the one in the migration's enum and from the one on
        # the wire. The other enums here are unaffected because their names equal their values.
        Enum(WebhookEvent, name="webhook_event", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    #: The exact bytes that were signed and sent. Kept so a receiver disputing a signature can
    #: be answered, and so a redelivery is the same event rather than a fresh snapshot of a
    #: record that has since changed.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="webhook_delivery_status"),
        nullable=False,
        default=DeliveryStatus.pending,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The receiver's status code, when there was one. Null means the request never completed.
    last_response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # The worker's query: due deliveries, oldest first, within one tenant.
        Index("ix_webhook_delivery_due", "agency_id", "status", "next_attempt_at"),
        Index("ix_webhook_delivery_subscription", "subscription_id"),
    )
