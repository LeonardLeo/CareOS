"""Phase 3 tables — payer contracts, authorizations, claims, remittance.

Present in the schema from the first release and unused until Phase 3, per
`04_Data_Model_and_Schema.md` Section 5. The point of shipping them early is
`ClaimLine.scheduled_visit_id`: every claim line traces directly back to the EVV-verified
visit that produced it. That lineage is what makes denial root-causing tractable, and it is
only cheap if the columns existed all along.

No Phase 3 endpoints or business logic exist yet. Do not build against these without the
certified billing/coding consultant review required by
`06_Compliance_and_Regulatory_Requirements.md` Section 9.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from careos.db.base import Base, PrimaryKeyMixin, TenantMixin, TimestampMixin


class ClaimStatus(enum.StrEnum):
    draft = "draft"
    scrubbed = "scrubbed"
    submitted = "submitted"
    accepted = "accepted"
    rejected = "rejected"
    paid = "paid"
    denied = "denied"


class PayerContract(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "payer_contract"

    payer_name: Mapped[str] = mapped_column(Text, nullable=False)
    payer_type: Mapped[str] = mapped_column(Text, nullable=False)
    state_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Non-secret clearinghouse routing only. EDI credentials live in the secrets manager.
    edi_connection_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class Authorization(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "authorization"
    __table_args__ = (
        # Mirrors migration 0005, so `alembic check` compares like with like.
        CheckConstraint(
            "units_used >= 0 AND authorized_units >= 0",
            name="ck_authorization_units_non_negative",
        ),
    )

    care_plan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("care_plan.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    payer_contract_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payer_contract.id", ondelete="RESTRICT"), nullable=False
    )
    authorized_units: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    #: Drives the exhaustion alerts in US-3.1.2.
    units_used: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    auth_start: Mapped[date] = mapped_column(Date, nullable=False)
    auth_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    authorization_number: Mapped[str | None] = mapped_column(Text, nullable=True)


class Claim(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "claim"

    payer_contract_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payer_contract.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[ClaimStatus] = mapped_column(
        SAEnum(ClaimStatus, name="claim_status"), nullable=False, default=ClaimStatus.draft
    )
    edi_837_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_billed_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)


class ClaimLine(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "claim_line"
    # A visit may legitimately be billed to more than one payer over time (a corrected
    # resubmission), but never twice on the same claim.
    __table_args__ = (
        Index("uq_claim_line_claim_visit", "claim_id", "scheduled_visit_id", unique=True),
    )

    claim_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("claim.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Direct traceability from a claim line back to the EVV-verified visit.
    scheduled_visit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scheduled_visit.id", ondelete="RESTRICT"), nullable=False
    )
    authorization_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("authorization.id", ondelete="RESTRICT"), nullable=True
    )
    billed_units: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    #: Output of the claim-scrubbing engine — the same rules engine Phase 1 uses for EVV
    #: exceptions, run against claim data (PRD Section 6).
    scrub_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class Remittance(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "remittance"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("claim.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    edi_835_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    adjustment_reason_codes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    #: Feeds the denial-management queue and its root-cause categorization (US-3.3.2).
    denial_category: Mapped[str | None] = mapped_column(Text, nullable=True)
