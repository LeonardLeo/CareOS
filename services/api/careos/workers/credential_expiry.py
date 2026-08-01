"""Announcing credentials that are about to expire (`05_API_Specification.md` Section 7).

The one event in Section 7 that is driven by the calendar rather than by something a user did:
nothing *happens* when a credential enters its 30-day window, the date simply arrives. That
makes this a job rather than a hook in a request path, and it makes repetition the problem to
solve — "expires in 12 days" is true again tomorrow, and a naive daily run would re-announce
every expiring credential every day until the agency muted the subscription.

`dedupe_on` handles that: a notice is sent once per credential per horizon. Crossing into a
tighter horizon *is* a new event and is announced again, which is the point of having 60/30/7
rather than one reminder.

Payload is identifiers and dates only — deliberately not `caregiver_name`, even though the
dashboard query hands it over. Section 7 asks for "caregiver ID, credential type, days until
expiration", and a receiver that wants the name can fetch it with a token.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

import structlog

from careos.db.session import tenant_session
from careos.modules.credentialing.service import expiring_credentials
from careos.modules.webhooks import service
from careos.modules.webhooks.models import WebhookEvent

logger = structlog.get_logger(__name__)


@dataclass
class ExpiryAnnounceRun:
    #: Credentials the dashboard query returned — expiring or already expired.
    considered: int = 0
    #: Deliveries queued. Zero when every notice was already sent, and also zero when the
    #: agency has no subscription for this event; the two are not distinguished here because
    #: neither is a problem.
    queued: int = 0


async def announce_expiring_credentials(
    agency_id: uuid.UUID, *, as_of: date | None = None
) -> ExpiryAnnounceRun:
    """Queue `credential.expiring_soon` for one agency's expiring credentials.

    Tenant-scoped like the other workers: the session's tenant context drives RLS, so this
    cannot reach another agency's credentials even if the loop calling it is wrong.
    """
    run = ExpiryAnnounceRun()

    async with tenant_session(agency_id) as session:
        for credential in await expiring_credentials(session, as_of=as_of):
            run.considered += 1
            queued = await service.enqueue(
                session,
                agency_id=agency_id,
                event=WebhookEvent.credential_expiring_soon,
                payload={
                    "credential_id": str(credential.credential_id),
                    "caregiver_id": str(credential.caregiver_id),
                    "credential_type": credential.credential_type,
                    "expiration_date": credential.expiration_date.isoformat(),
                    "days_until_expiry": credential.days_until_expiry,
                    "bucket": credential.bucket,
                    "already_expired": credential.already_expired,
                },
                # The horizon is part of the identity, so the 30-day notice does not suppress
                # the 7-day one. `days_until_expiry` deliberately is not: it changes daily and
                # would make every run a new event again.
                dedupe_on={
                    "credential_id": str(credential.credential_id),
                    "bucket": credential.bucket,
                },
            )
            run.queued += len(queued)

    if run.queued:
        logger.info(
            "webhook.credential_expiry_announced",
            agency_id=str(agency_id),
            considered=run.considered,
            queued=run.queued,
        )
    return run
