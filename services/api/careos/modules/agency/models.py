"""Tenant and user records — `agency` module (`03_Technical_Architecture.md` Section 4)."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from careos.db.base import Base, PrimaryKeyMixin, TimestampMixin


class ServiceLine(enum.StrEnum):
    home_care = "home_care"
    home_health = "home_health"
    hospice = "hospice"


class PayerType(enum.StrEnum):
    medicaid_waiver = "medicaid_waiver"
    medicare_advantage = "medicare_advantage"
    private_pay = "private_pay"
    other = "other"


class Role(enum.StrEnum):
    """Roles from `04_Data_Model_and_Schema.md` Section 3 / `08_Security_Architecture.md`."""

    owner_admin = "owner_admin"
    scheduler = "scheduler"
    clinical_supervisor = "clinical_supervisor"
    caregiver = "caregiver"
    billing_rcm = "billing_rcm"
    auditor = "auditor"


class UserStatus(enum.StrEnum):
    invited = "invited"
    active = "active"
    suspended = "suspended"


class Agency(Base, PrimaryKeyMixin, TimestampMixin):
    """The tenant root. Its `id` is the tenant key carried by every other table."""

    __tablename__ = "agency"

    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Encrypted at the application layer before it reaches Postgres — field-level
    # encryption for tax ID is required by `08_Security_Architecture.md` Section 3.
    tax_id_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    #: Drives which EVV aggregator adapter and compliance rule set applies (US-1.1.1).
    service_states: Mapped[list[str]] = mapped_column(
        ARRAY(String(2)), nullable=False, default=list
    )
    service_lines: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    accepted_payer_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    #: Multi-location rollups (US-1.1.3). Franchise billing/royalty is explicitly out of scope.
    parent_org_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agency.id", ondelete="RESTRICT"), nullable=True
    )


class AppUser(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("email", name="uq_app_user_email"),)

    agency_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agency.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    role: Mapped[Role] = mapped_column(SAEnum(Role, name="user_role"), nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Subject ID from the managed IdP. `08_Security_Architecture.md` Section 1 calls for
    #: OAuth2/OIDC via a managed provider rather than bespoke auth; this column is that
    #: seam. The local password hash below exists so the system is runnable and testable
    #: before the IdP is provisioned, and is expected to go away at that point.
    auth_provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, name="user_status"), nullable=False, default=UserStatus.invited
    )
    #: MFA is required for owner_admin / clinical_supervisor / billing_rcm
    #: (`08_Security_Architecture.md` Section 1). Enrolment state is tracked here so the
    #: requirement is enforceable at login rather than assumed.
    mfa_enrolled: Mapped[bool] = mapped_column(nullable=False, default=False)


#: Roles for which MFA is mandatory, not advisory.
MFA_REQUIRED_ROLES: frozenset[Role] = frozenset(
    {Role.owner_admin, Role.clinical_supervisor, Role.billing_rcm}
)
