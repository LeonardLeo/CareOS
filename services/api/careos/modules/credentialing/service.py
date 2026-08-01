"""Credentialing domain logic — Epic 1.3."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core.audit import AuditAction, record_audit
from careos.core.errors import NotFoundError
from careos.core.security import Principal
from careos.modules.credentialing.models import Caregiver, Credential, VerificationStatus

#: Reminder horizons from US-1.3.3. Descending, so a credential is reported in the most
#: urgent bucket it qualifies for rather than every bucket it fits.
RENEWAL_HORIZONS_DAYS: tuple[int, ...] = (7, 30, 60)


@dataclass(slots=True)
class ExpiringCredential:
    credential_id: uuid.UUID
    caregiver_id: uuid.UUID
    caregiver_name: str
    credential_type: str
    expiration_date: date
    days_until_expiry: int
    #: 7, 30, or 60 — the tightest horizon this falls into. Negative days land in bucket 0.
    bucket: int
    #: True once expired: the caregiver can no longer be assigned visits on or after this
    #: date, which `assert_assignable` enforces.
    already_expired: bool


async def add_credential(
    session: AsyncSession,
    *,
    principal: Principal,
    caregiver_id: uuid.UUID,
    credential_type: str,
    issuing_body: str | None,
    credential_number: str | None,
    issue_date: date | None,
    expiration_date: date | None,
    verification_status: VerificationStatus,
) -> Credential:
    caregiver = await session.get(Caregiver, caregiver_id)
    if caregiver is None:
        raise NotFoundError("Caregiver not found")

    credential = Credential(
        agency_id=principal.agency_id,
        caregiver_id=caregiver_id,
        credential_type=credential_type,
        issuing_body=issuing_body,
        credential_number=credential_number,
        issue_date=issue_date,
        expiration_date=expiration_date,
        verification_status=verification_status,
    )
    session.add(credential)
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=(
            AuditAction.credential_verified
            if verification_status is VerificationStatus.verified
            else AuditAction.credential_added
        ),
        entity_type="credential",
        entity_id=credential.id,
        after_state={
            "caregiver_id": str(caregiver_id),
            "credential_type": credential_type,
            "verification_status": verification_status.value,
            "expiration_date": expiration_date.isoformat() if expiration_date else None,
        },
    )
    return credential


async def expiring_credentials(
    session: AsyncSession, *, as_of: date | None = None, horizon_days: int = 60
) -> list[ExpiringCredential]:
    """Credentials expiring within `horizon_days`, plus any already expired (US-1.3.3).

    Already-expired credentials are included rather than filtered out. They are the most
    urgent case — the caregiver is unassignable right now — and a dashboard that only looks
    forward would hide exactly the problem the agency most needs to fix.
    """
    today = as_of or datetime.now(UTC).date()
    cutoff = today + timedelta(days=horizon_days)

    rows = (
        await session.execute(
            select(Credential, Caregiver.legal_name)
            .join(Caregiver, Caregiver.id == Credential.caregiver_id)
            .where(
                Credential.expiration_date.is_not(None),
                Credential.expiration_date <= cutoff,
                Credential.verification_status != VerificationStatus.rejected,
            )
            .order_by(Credential.expiration_date)
        )
    ).all()

    results: list[ExpiringCredential] = []
    for credential, caregiver_name in rows:
        days = (credential.expiration_date - today).days
        bucket = 0
        for horizon in RENEWAL_HORIZONS_DAYS:
            if days <= horizon:
                bucket = horizon
                break
        results.append(
            ExpiringCredential(
                credential_id=credential.id,
                caregiver_id=credential.caregiver_id,
                caregiver_name=caregiver_name,
                credential_type=credential.credential_type,
                expiration_date=credential.expiration_date,
                days_until_expiry=days,
                bucket=bucket if days >= 0 else 0,
                already_expired=days < 0,
            )
        )
    return results
