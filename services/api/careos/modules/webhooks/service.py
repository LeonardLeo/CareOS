"""Enqueuing, signing, and validating outbound webhooks.

Delivery itself lives in `careos.workers.webhook_delivery`; this module is what a request path
touches, and everything here runs inside the caller's transaction.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.config import get_settings
from careos.core.errors import ValidationError
from careos.modules.webhooks.models import (
    DeliveryStatus,
    SubscriptionStatus,
    WebhookDelivery,
    WebhookEvent,
    WebhookSubscription,
)

logger = structlog.get_logger(__name__)

#: Header carrying the signature, in the form `t=<unix seconds>,v1=<hex hmac>`.
SIGNATURE_HEADER = "CareOS-Signature"
EVENT_HEADER = "CareOS-Event"
DELIVERY_HEADER = "CareOS-Delivery"

#: How far a receiver should let a timestamp drift before rejecting it. Not enforced here —
#: it is the receiver's check — but published so an integrator implements the same window.
SIGNATURE_TOLERANCE_SECONDS = 300

#: Consecutive failures after which a subscription is disabled. High enough to ride out a
#: deploy or a short outage at the receiver, low enough that a permanently dead URL stops
#: accumulating a queue that will never drain.
FAILURES_BEFORE_DISABLE = 20

#: Attempts per delivery before it is abandoned, and the backoff between them in seconds.
#: Front-loaded for a receiver that restarted, then widening to hours for one that is down.
RETRY_BACKOFF_SECONDS = (0, 30, 120, 600, 3_600, 21_600)
MAX_ATTEMPTS = len(RETRY_BACKOFF_SECONDS)

#: Field names that must never appear in a webhook payload, at any depth.
#:
#: `05_API_Specification.md` Section 7 describes payloads made of identifiers and statuses, and
#: this is that description turned into a rule. A webhook is an unauthenticated push to a URL an
#: agency administrator typed into a form, delivered over the public internet to a system CareOS
#: has no BAA with. A receiver needing more than an id can fetch it from the API with a token.
#:
#: Matched on the key rather than the value, because a value-based check cannot tell a name from
#: any other string — and a rule that only catches what it recognises is not a boundary.
PHI_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "address",
        "address_encrypted",
        "client_name",
        "dob",
        "dob_encrypted",
        "date_of_birth",
        "email",
        "full_name",
        "geo",
        "geo_lat",
        "geo_lng",
        "legal_name",
        "caregiver_name",
        "notes",
        "phone",
        "ssn",
        "street_address",
        "tax_id",
        "tax_id_encrypted",
    }
)


class WebhookPayloadError(RuntimeError):
    """A payload was rejected before it could be queued. A bug, not a user error."""


def assert_payload_carries_no_phi(payload: Any, *, path: str = "") -> None:
    """Refuse a payload containing a field named like PHI, at any depth.

    Raised as a `RuntimeError` rather than returned as a validation failure because it can only
    be reached by application code building an event — an agency cannot cause it. The point is
    to fail the request that tried, loudly, rather than to deliver.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            here = f"{path}.{key}" if path else key
            if key.lower() in PHI_FIELD_NAMES:
                raise WebhookPayloadError(
                    f"Webhook payload field {here!r} looks like PHI. Webhook payloads carry "
                    "identifiers and status only (05_API_Specification.md Section 7); a "
                    "receiver that needs more should fetch it from the API with a token."
                )
            assert_payload_carries_no_phi(value, path=here)
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            assert_payload_carries_no_phi(value, path=f"{path}[{index}]")


def _is_private_host(host: str) -> bool:
    """Whether a hostname resolves only to addresses inside the deployment's own network.

    The URL comes from a form an agency administrator fills in, which makes an unrestricted
    webhook a request forwarder: point it at `http://169.254.169.254/` and CareOS fetches cloud
    instance credentials on their behalf, or at an internal admin service and it becomes a way
    to reach one from outside. Resolving here narrows the window but does not close it — DNS can
    answer differently at delivery time — so the worker checks again before it connects.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Unresolvable now is not proof of anything; the delivery-time check is the backstop.
        return False
    for info in infos:
        address = info[4][0]
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if (
            parsed.is_private
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_reserved
            or parsed.is_unspecified
        ):
            return True
    return False


def validate_subscription_url(url: str) -> str:
    """Check a subscription URL, or raise a `ValidationError` explaining why not."""
    parsed = urlparse(url)

    settings = get_settings()
    allowed_schemes = {"https"} if settings.is_production else {"https", "http"}
    if parsed.scheme not in allowed_schemes:
        raise ValidationError(
            "Webhook URLs must use https. Payloads are signed but not encrypted by the "
            "signature, and plain http would put event identifiers on the wire in the clear.",
            details={"url": url, "scheme": parsed.scheme},
        )
    if not parsed.hostname:
        raise ValidationError("Webhook URL has no host.", details={"url": url})

    if settings.is_production and _is_private_host(parsed.hostname):
        raise ValidationError(
            "Webhook URL resolves to a private or loopback address. CareOS will not deliver "
            "to its own network on a customer's behalf.",
            details={"url": url, "host": parsed.hostname},
        )
    return url


def is_forbidden_target(url: str) -> bool:
    """Whether this URL must not be connected to, checked at delivery time.

    Separate from `validate_subscription_url` because the two run at different moments and
    only one of them can be trusted: subscription time is a courtesy that gives the agency a
    clear error, delivery time is the check that actually prevents the request. Outside
    production this returns False, or no local integration could ever be tested.
    """
    if not get_settings().is_production:
        return False
    host = urlparse(url).hostname
    return host is not None and _is_private_host(host)


def generate_signing_secret() -> str:
    """A secret the receiver uses to verify signatures. Shown once, at creation."""
    return f"whsec_{secrets.token_urlsafe(32)}"


def canonical_body(payload: dict[str, Any]) -> bytes:
    """The exact bytes signed and sent.

    Serialized once and reused, rather than re-serialized at send time: two `json.dumps` calls
    can differ in key order or whitespace, and a signature over different bytes than were sent
    fails verification at the receiver for reasons nobody can reproduce.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(body: bytes, secret: str, *, timestamp: int | None = None) -> str:
    """Build the `CareOS-Signature` header value.

    The timestamp is inside the signed material, not just alongside it. Signing the body alone
    would let anyone who captured one delivery replay it forever; with the timestamp signed, a
    receiver enforcing `SIGNATURE_TOLERANCE_SECONDS` has a window instead of an eternity.

    `v1=` prefixes the digest so a future scheme can be added without receivers guessing which
    one they are looking at.
    """
    ts = timestamp if timestamp is not None else int(datetime.now(UTC).timestamp())
    signed = f"{ts}.".encode() + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def verify(header_value: str, body: bytes, secret: str, *, tolerance: int | None = None) -> bool:
    """Verify a signature the way a receiver should.

    Lives here so the test suite checks the algorithm an integrator will implement, rather than
    a second implementation of it that could agree with itself and with nothing else.
    """
    parts = dict(piece.split("=", 1) for piece in header_value.split(",") if "=" in piece)
    ts_raw, digest = parts.get("t"), parts.get("v1")
    if not ts_raw or not digest:
        return False
    if not re.fullmatch(r"\d+", ts_raw):
        return False

    window = SIGNATURE_TOLERANCE_SECONDS if tolerance is None else tolerance
    age = abs(int(datetime.now(UTC).timestamp()) - int(ts_raw))
    if age > window:
        return False

    expected = hmac.new(secret.encode(), f"{ts_raw}.".encode() + body, hashlib.sha256).hexdigest()
    # Constant time: a byte-by-byte comparison leaks how much of a forged digest was right.
    return hmac.compare_digest(expected, digest)


async def _already_queued(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
    event: WebhookEvent,
    dedupe_on: dict[str, Any],
) -> bool:
    """Whether this subscription has already been sent a matching event."""
    existing = await session.execute(
        select(WebhookDelivery.id)
        .where(
            WebhookDelivery.subscription_id == subscription_id,
            WebhookDelivery.event == event,
            # JSONB containment: the stored payload must contain these keys and values. Only
            # the identifying subset is compared, so a field that legitimately changes between
            # runs — "12 days until expiry" becoming "11" — is not a different event.
            WebhookDelivery.payload.contains(dedupe_on),
        )
        .limit(1)
    )
    return existing.first() is not None


async def enqueue(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    event: WebhookEvent,
    payload: dict[str, Any],
    dedupe_on: dict[str, Any] | None = None,
) -> list[WebhookDelivery]:
    """Queue an event for every active subscription that wants it.

    Called from inside the transaction that made the change being announced, so a rollback
    takes the unsent webhook with it. Returns the queued rows, mostly so a test can assert on
    them; callers normally ignore the result.

    `dedupe_on` names the subset of the payload that identifies the event, and suppresses a
    second delivery to a subscription that already has a matching one. It exists for producers
    driven by a *state* rather than by a change — "this credential expires in 12 days" is true
    again tomorrow, and a daily job without this would re-announce it every day until it either
    expired or the agency turned the subscription off. Left `None` for change-driven events,
    where the caller's transaction already guarantees the event happened exactly once, and
    where the extra query per subscription would sit on a clock-in.
    """
    assert_payload_carries_no_phi(payload)

    subscriptions = (
        (
            await session.execute(
                select(WebhookSubscription).where(
                    WebhookSubscription.status == SubscriptionStatus.active
                )
            )
        )
        .scalars()
        .all()
    )

    queued: list[WebhookDelivery] = []
    now = datetime.now(UTC)
    for subscription in subscriptions:
        if event.value not in (subscription.events or []):
            continue
        if dedupe_on is not None and await _already_queued(
            session, subscription_id=subscription.id, event=event, dedupe_on=dedupe_on
        ):
            continue
        delivery = WebhookDelivery(
            agency_id=agency_id,
            subscription_id=subscription.id,
            event=event,
            payload=payload,
            status=DeliveryStatus.pending,
            next_attempt_at=now,
        )
        session.add(delivery)
        queued.append(delivery)

    if queued:
        logger.info(
            "webhook.enqueued",
            # Not `event=`: structlog uses that key for the message itself, so passing it
            # here raises "got multiple values for argument 'event'" — at enqueue time, which
            # is inside the caller's transaction and would fail their request.
            webhook_event=event.value,
            subscriptions=len(queued),
            agency_id=str(agency_id),
        )
    return queued
