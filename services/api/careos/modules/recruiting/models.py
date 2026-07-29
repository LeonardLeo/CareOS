"""Job postings and the applicant pipeline — `recruiting` module."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from careos.db.base import Base, PrimaryKeyMixin, TenantMixin, TimestampMixin


class PipelineStage(enum.StrEnum):
    applied = "applied"
    screened = "screened"
    offer = "offer"
    hired = "hired"
    rejected = "rejected"


class JobPosting(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "job_posting"

    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_credential_types: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    service_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Per-board syndication state, keyed by board adapter key. Normalizing this into its
    #: own table is premature until a second board is live.
    syndication_status: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")


class ApplicantProfile(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "applicant_profile"

    job_posting_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("job_posting.id", ondelete="SET NULL"), nullable=True
    )
    #: Normalized regardless of inbound board (`07_Integration_Specifications.md` Section 4).
    source: Mapped[str] = mapped_column(Text, nullable=False, default="direct")
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_credentials: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    availability: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    resume_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    geo_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    geo_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)

    ranking_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    #: Explainability is a hard requirement, not a UI nicety: US-1.2.2 requires the top
    #: factors behind every score, and the fair-hiring posture in
    #: `06_Compliance_and_Regulatory_Requirements.md` Section 5 depends on scores being
    #: auditable after the fact. A score written without factors is a bug.
    ranking_factors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    ranked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Version of the ranking prompt/model that produced the score, so a later bias audit
    #: can attribute decisions to a specific model revision.
    ranking_model_version: Mapped[str | None] = mapped_column(Text, nullable=True)

    pipeline_stage: Mapped[PipelineStage] = mapped_column(
        SAEnum(PipelineStage, name="pipeline_stage"), nullable=False, default=PipelineStage.applied
    )
    stage_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
