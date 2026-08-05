"""Clients, care plans, visits, and EVV records — `scheduling` module.

This is the compliance-critical core of Phase 1. Two things here are load-bearing for
phases that are not built yet, and must not be treated as optional:

* `ScheduledVisit` carries the payer/service-code triple from Phase 1 onward, even though
  nothing consumes it until Phase 3. `03_Technical_Architecture.md` Section 6 is explicit
  that backfilling these onto historical visits later is expensive and error-prone.
* `EVVRecord.six_element_snapshot` is an immutable record of exactly what was transmitted,
  not a view derived from live rows — an audit two years from now must see what the state
  aggregator saw, not what the data has since become.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from careos.db.base import Base, PrimaryKeyMixin, TenantMixin, TimestampMixin


class ClientStatus(enum.StrEnum):
    active = "active"
    on_hold = "on_hold"
    discharged = "discharged"


class VisitStatus(enum.StrEnum):
    open = "open"
    assigned = "assigned"
    confirmed = "confirmed"
    in_progress = "in_progress"
    completed = "completed"
    missed = "missed"
    cancelled = "cancelled"


class CaptureMethod(enum.StrEnum):
    """How the six EVV elements were captured.

    `telephony` and `manual_exception` are first-class, not degraded paths: caregivers
    without smartphones or signal must still be able to clock in
    (`02_Product_Requirements_Document.md` US-1.4.3, `09_UX...` design principle 2).
    """

    mobile_gps = "mobile_gps"
    telephony = "telephony"
    manual_exception = "manual_exception"


class TransmissionStatus(enum.StrEnum):
    """A visit is compliant only at `acknowledged`.

    `07_Integration_Specifications.md` Section 2: "a visit is not 'compliant' until
    transmission is acknowledged, not merely submitted."
    """

    pending = "pending"
    transmitted = "transmitted"
    acknowledged = "acknowledged"
    rejected = "rejected"


class Client(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "client"

    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    dob_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    address_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    #: Coarse coordinates for the visit geofence and drive-time matching. The precise
    #: street address stays encrypted above; this is the operational projection of it.
    geo_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    geo_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    #: State of service delivery — selects the EVV adapter and the compliance rule set.
    service_state: Mapped[str] = mapped_column(String(2), nullable=False)
    primary_payer_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ClientStatus] = mapped_column(
        SAEnum(ClientStatus, name="client_status"), nullable=False, default=ClientStatus.active
    )


class CarePlan(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "care_plan"

    client_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("client.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    #: Authorized ADLs/tasks. Phase 2's in-visit checklist and the structured-extraction
    #: schema both read from this, so the shape is deliberately open.
    authorized_tasks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: RRULE-style recurrence consumed by visit materialization.
    visit_frequency_rule: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    effective_start: Mapped[date] = mapped_column(Date, nullable=False)
    effective_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    clinical_supervisor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    #: Service code the visits generated from this plan inherit. Phase 3 bills against it.
    default_service_type_code: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScheduledVisit(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "scheduled_visit"
    __table_args__ = (
        # Composite FK into the reference table: a service code is only meaningful together
        # with the state and payer type it belongs to (`06_Compliance...` Section 4).
        ForeignKeyConstraint(
            ["service_type_code", "service_state", "payer_type"],
            [
                "payer_service_code_ref.code",
                "payer_service_code_ref.state_code",
                "payer_service_code_ref.payer_type",
            ],
            name="fk_scheduled_visit_service_code",
            ondelete="RESTRICT",
        ),
        Index("ix_scheduled_visit_agency_start", "agency_id", "scheduled_start"),
        Index("ix_scheduled_visit_caregiver_start", "caregiver_id", "scheduled_start"),
        # Declared here as well as in migration 0003 because `alembic check` compares the
        # models against the database: a constraint that exists only in a migration reads as
        # one the schema is about to lose.
        CheckConstraint("scheduled_end > scheduled_start", name="ck_scheduled_visit_end_after_start"),
    )

    care_plan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("care_plan.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    caregiver_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("caregiver.id", ondelete="RESTRICT"), nullable=True
    )
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[VisitStatus] = mapped_column(
        SAEnum(VisitStatus, name="visit_status"), nullable=False, default=VisitStatus.open
    )

    # --- Billing-relevant fields, populated from Phase 1, consumed in Phase 3 ----------
    service_type_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    service_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    payer_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Set in Phase 3. The column ships from Phase 1; the constraint is added in migration
    #: 0005, once the `authorization` table it points at exists.
    authorization_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "authorization.id", ondelete="RESTRICT", name="fk_scheduled_visit_authorization"
        ),
        nullable=True,
    )

    #: Tasks copied from the care plan at materialization time. Snapshotted rather than
    #: read through, so amending a care plan does not silently rewrite past visits.
    required_tasks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: Deduplication key for offline-generated visits/actions (API spec Section 4).
    client_local_uuid: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)


class EVVRecord(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "evv_record"
    __table_args__ = (
        # Partial index over the retry queue. The transmission worker only ever scans rows
        # that have not reached a terminal state, and in steady state that is a small
        # minority of the table.
        Index(
            "ix_evv_record_untransmitted",
            "agency_id",
            "last_transmission_at",
            postgresql_where=text("transmission_status IN ('pending', 'transmitted')"),
        ),
        CheckConstraint(
            "clock_out_time IS NULL OR clock_in_time IS NULL OR clock_out_time >= clock_in_time",
            name="ck_evv_record_clock_order",
        ),
    )

    scheduled_visit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scheduled_visit.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    clock_in_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clock_out_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clock_in_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    clock_in_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    clock_out_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    clock_out_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    capture_method: Mapped[CaptureMethod] = mapped_column(
        SAEnum(CaptureMethod, name="capture_method"), nullable=False
    )
    transmission_status: Mapped[TransmissionStatus] = mapped_column(
        SAEnum(TransmissionStatus, name="transmission_status"),
        nullable=False,
        default=TransmissionStatus.pending,
    )
    transmission_attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    last_transmission_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Raw aggregator response, kept for audit and for debugging rejections.
    aggregator_response_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    aggregator_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The six federally required elements exactly as transmitted. Written once, at
    #: transmission time, and never recomputed.
    six_element_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: Offline sync dedup: the mobile app generates this before it has connectivity.
    client_local_uuid: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)


class ComplianceException(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    """An open compliance problem needing agency attention (US-1.4.6).

    Produced by the compliance-rules engine. Deliberately generic — Phase 2 documentation
    flags and Phase 3 claim-scrub findings land in this same table rather than each phase
    inventing its own exception queue.
    """

    __tablename__ = "compliance_exception"
    __table_args__ = (
        Index("ix_compliance_exception_open", "agency_id", "resolved_at"),
        # One open exception per rule per entity. Re-running the rules engine on every
        # clock-out would otherwise pile up duplicates and bury the scheduler in noise.
        Index(
            "uq_compliance_exception_open_rule_entity",
            "agency_id",
            "rule_key",
            "entity_type",
            "entity_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )

    rule_key: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
