"""Phase 2 tables — visit notes and ambient-documentation metadata.

These ship in the schema now, unused, per the "design for Phase 3 from Phase 1" principle
(`03_Technical_Architecture.md` Section 1). No Phase 2 endpoints exist yet.

The consent columns on `AmbientSessionMetadata` are not bookkeeping. Two-party consent
states require the client's consent, not just the caregiver's, before any recording begins
(`06_Compliance_and_Regulatory_Requirements.md` Section 6), and the transcription adapter
validates consent independently of the UI as defence in depth
(`07_Integration_Specifications.md` Section 5).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from careos.db.base import Base, PrimaryKeyMixin, TenantMixin, TimestampMixin


class ConsentMethod(enum.StrEnum):
    verbal_logged = "verbal_logged"
    written = "written"


class AmbientSessionMetadata(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "ambient_session_metadata"
    __table_args__ = (Index("ix_ambient_session_metadata_visit", "scheduled_visit_id"),)

    scheduled_visit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scheduled_visit.id", ondelete="RESTRICT"),
        nullable=False,
    )
    #: Must be true before any audio is processed. Enforced in the service layer and
    #: re-checked in the transcription adapter.
    consent_captured: Mapped[bool] = mapped_column(nullable=False, default=False)
    consent_method: Mapped[ConsentMethod | None] = mapped_column(
        SAEnum(ConsentMethod, name="consent_method"), nullable=True
    )
    consent_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Default is transcript-only retention. Raw audio is kept only where the agency has
    #: opted in with appropriate consent (`06_Compliance...` Section 6).
    audio_retained: Mapped[bool] = mapped_column(nullable=False, default=False)
    audio_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)


class VisitNote(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "visit_note"
    __table_args__ = (Index("ix_visit_note_visit", "scheduled_visit_id"),)

    scheduled_visit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scheduled_visit.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ambient_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ambient_session_metadata.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Extracted fields matched against `care_plan.authorized_tasks`.
    structured_content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    narrative_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Human sign-off is unskippable (`09_UX...` design principle 5). A note with a null
    #: `caregiver_signed_at` is a draft and is never billable.
    caregiver_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    supervisor_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    supervisor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    #: Output of the shared compliance-rules engine.
    compliance_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
