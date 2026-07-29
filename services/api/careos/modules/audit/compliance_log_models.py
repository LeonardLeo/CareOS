"""Durable record of compliance reviews.

`06_Compliance_and_Regulatory_Requirements.md` Section 9 sets a review cadence — counsel
review before each phase launch, consent-law review per state, an annual re-check of CMS rules
and state EVV vendors, and a re-run of the AI hiring bias audit — and
`12_Engineering_Handoff_Guide.md` Section 5 is blunt about why it must be written down:
"we did a review once" is not useful to a future team without knowing when and what.

So reviews are rows, not folklore. Two consequences fall out of that:

* **Overdue reviews are computable.** `ComplianceReview.is_overdue` turns the cadence into
  something a dashboard or CI job can check, instead of something a person has to remember.
* **The bias audit records itself.** `careos.scripts.run_bias_audit` writes its outcome here
  automatically, so the audit evidence and the audit run cannot drift apart.

This table is tenant-scoped: each agency's obligations are its own, and a review performed for
one agency's state footprint says nothing about another's.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from careos.db.base import Base, PrimaryKeyMixin, TenantMixin, TimestampMixin


class ReviewType(enum.StrEnum):
    """The review triggers enumerated in `06_Compliance...` Section 9."""

    healthcare_counsel = "healthcare_counsel"
    consent_law_state = "consent_law_state"
    billing_coding_consultant = "billing_coding_consultant"
    ai_hiring_bias_audit = "ai_hiring_bias_audit"
    cms_pps_rule_review = "cms_pps_rule_review"
    evv_vendor_review = "evv_vendor_review"
    new_state_entry = "new_state_entry"
    security_penetration_test = "security_penetration_test"


class ReviewOutcome(enum.StrEnum):
    passed = "passed"
    passed_with_findings = "passed_with_findings"
    failed = "failed"
    #: Ran, but the result was not conclusive — e.g. a bias audit on too small a sample.
    inconclusive = "inconclusive"


#: How often each review must be repeated. `None` means it is triggered by an event (a phase
#: launch, entering a new state) rather than by the calendar, so it cannot go "overdue" on a
#: schedule and is excluded from the overdue check.
REVIEW_CADENCE_DAYS: dict[ReviewType, int | None] = {
    ReviewType.healthcare_counsel: 365,
    ReviewType.consent_law_state: None,
    ReviewType.billing_coding_consultant: None,
    # Section 9 puts the bias audit on an annual cadence, and Section 5 additionally requires
    # a re-audit whenever the model or its inputs change — which the cadence cannot express,
    # so `model_version` is recorded to make that check possible.
    ReviewType.ai_hiring_bias_audit: 365,
    ReviewType.cms_pps_rule_review: 365,
    ReviewType.evv_vendor_review: 365,
    ReviewType.new_state_entry: None,
    ReviewType.security_penetration_test: 365,
}


class ComplianceReview(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "compliance_review"
    __table_args__ = (
        Index("ix_compliance_review_type_date", "agency_id", "review_type", "performed_on"),
    )

    review_type: Mapped[ReviewType] = mapped_column(
        SAEnum(ReviewType, name="compliance_review_type"), nullable=False
    )
    performed_on: Mapped[date] = mapped_column(Date, nullable=False)
    outcome: Mapped[ReviewOutcome] = mapped_column(
        SAEnum(ReviewOutcome, name="compliance_review_outcome"), nullable=False
    )
    #: Who performed it — counsel firm, consultant, or an automated job name. Free text
    #: because it is as often a person or firm as it is a system.
    performed_by: Mapped[str] = mapped_column(Text, nullable=False)
    #: Scope, e.g. the state or model version reviewed. Vital for a future team: an EVV
    #: review covering New York says nothing about Texas.
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: For the bias audit: which model revision was assessed.
    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Full machine-readable result, e.g. an `AuditReport.as_dict()`.
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    next_due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def compute_next_due(self) -> date | None:
        cadence = REVIEW_CADENCE_DAYS.get(self.review_type)
        if cadence is None:
            return None
        from datetime import timedelta

        return self.performed_on + timedelta(days=cadence)

    def is_overdue(self, as_of: date | None = None) -> bool:
        if self.next_due_on is None:
            return False
        return self.next_due_on < (as_of or datetime.now(UTC).date())
