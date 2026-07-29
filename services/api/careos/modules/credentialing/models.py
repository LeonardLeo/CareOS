"""Caregivers, credentials, and the exclusion-list gate — `credentialing` module."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from careos.db.base import Base, PrimaryKeyMixin, TenantMixin, TimestampMixin


class EmploymentStatus(enum.StrEnum):
    applicant = "applicant"
    onboarding = "onboarding"
    active = "active"
    inactive = "inactive"
    terminated = "terminated"


class ExclusionCheckStatus(enum.StrEnum):
    """OIG LEIE + GSA SAM exclusion screening state.

    `not_run` and `flagged` both block Medicaid/Medicare-billed scheduling. Only `cleared`
    permits it — see `careos.modules.scheduling.service.assert_assignable`.
    """

    not_run = "not_run"
    cleared = "cleared"
    flagged = "flagged"


class VerificationStatus(enum.StrEnum):
    pending = "pending"
    verified = "verified"
    expired = "expired"
    rejected = "rejected"


class Caregiver(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "caregiver"

    app_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    #: Traceability back into the recruiting funnel (US-1.2.4 conversion reporting).
    applicant_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("applicant_profile.id", ondelete="SET NULL"), nullable=True
    )
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    # DOB and street address are field-level encrypted per `08_Security_Architecture.md`
    # Section 3: a database-layer compromise alone must not expose them in plaintext.
    dob_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    address_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    employment_status: Mapped[EmploymentStatus] = mapped_column(
        SAEnum(EmploymentStatus, name="employment_status"),
        nullable=False,
        default=EmploymentStatus.applicant,
    )
    exclusion_check_status: Mapped[ExclusionCheckStatus] = mapped_column(
        SAEnum(ExclusionCheckStatus, name="exclusion_check_status"),
        nullable=False,
        default=ExclusionCheckStatus.not_run,
    )
    #: Exclusion status is not "check once" (`07_Integration_Specifications.md` Section 3):
    #: recurring re-verification is expected, so we record when it last ran.
    exclusion_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Coarse coordinates for drive-time and proximity matching. Stored as plain numerics
    # rather than PostGIS geography: Phase 1 matching needs ranking, not spatial joins, and
    # this avoids a PostGIS dependency in the first migration. Revisit if routing moves
    # in-database.
    geo_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    geo_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)

    @property
    def is_exclusion_cleared(self) -> bool:
        return self.exclusion_check_status is ExclusionCheckStatus.cleared


class Credential(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "credential"

    caregiver_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("caregiver.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    credential_type: Mapped[str] = mapped_column(
        Text, ForeignKey("credential_type_ref.code", ondelete="RESTRICT"), nullable=False
    )
    issuing_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: Drives the 60/30/7-day renewal reminders in US-1.3.3.
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        SAEnum(VerificationStatus, name="verification_status"),
        nullable=False,
        default=VerificationStatus.pending,
    )
    document_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    def is_valid_on(self, on: date) -> bool:
        if self.verification_status is not VerificationStatus.verified:
            return False
        return self.expiration_date is None or self.expiration_date >= on


class ScreeningRequest(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    """One outstanding call to a background-check / exclusion-screening vendor.

    Modelled separately from `caregiver` because these are async and multi-result: a single
    onboarding kicks off criminal, sex-offender-registry, exclusion-list, and license checks
    in parallel (US-1.3.2), each resolving on its own webhook.
    """

    __tablename__ = "screening_request"

    caregiver_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("caregiver.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vendor_key: Mapped[str] = mapped_column(Text, nullable=False)
    check_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    vendor_request_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="initiated")
    result_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
