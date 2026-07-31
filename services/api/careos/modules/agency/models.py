"""Tenant and user records — `agency` module (`03_Technical_Architecture.md` Section 4)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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
    #: (`08_Security_Architecture.md` Section 1). True only once the user has *proved* a code,
    #: never merely because a secret was issued — an enrolment that was started and abandoned
    #: would otherwise lock the user out of an account they cannot produce codes for.
    mfa_enrolled: Mapped[bool] = mapped_column(nullable=False, default=False)
    #: The TOTP secret, encrypted with the same field key as DOB and tax ID. A second factor
    #: stored in plaintext is a second factor a database compromise hands over along with the
    #: password hashes it was meant to backstop.
    mfa_secret_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    #: The last TOTP counter this user successfully authenticated with. Stored so a code
    #: cannot be used twice inside its own thirty-second window — otherwise a code read over
    #: a shoulder or off a shared screen stays valid for as long as it is on display.
    mfa_last_counter: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: Argon2 hashes of the single-use recovery codes, hashed for the same reason passwords
    #: are: each one is a credential that bypasses the second factor.
    mfa_recovery_hashes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    #: Watermark for session revocation (`08_Security_Architecture.md` Section 6). Any access
    #: token whose `iat` is at or before this instant is refused, which cuts a terminated
    #: caregiver off from the API — and therefore from the cached PHI on their device, since
    #: the caregiver app wipes it on a rejected token. NULL means never revoked.
    sessions_revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Why this account was disabled, in the words of the administrator who did it. Kept on the
    #: row rather than only in the audit log because the question "why can this person not sign
    #: in?" is asked by whoever is looking at the user list, and an answer that requires an
    #: audit-log query is an answer most people will not get. Cleared when the account is
    #: re-enabled; the audit log keeps the history either way.
    disabled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


#: Roles for which MFA is mandatory, not advisory.
MFA_REQUIRED_ROLES: frozenset[Role] = frozenset(
    {Role.owner_admin, Role.clinical_supervisor, Role.billing_rcm}
)

#: Roles that may enrol an authenticator at all.
#:
#: Everything except `caregiver`, and that exclusion is a guard rather than a policy. The
#: caregiver app has no field to type a code into, so a caregiver who enrolled through the API
#: would be unable to sign in on the phone they clock in with — discovered at a client's door,
#: with no way to fix it themselves. Widening this is one line, once that app can ask.
MFA_ELIGIBLE_ROLES: frozenset[Role] = frozenset(set(Role) - {Role.caregiver})
