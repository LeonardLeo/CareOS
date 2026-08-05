"""Platform operators and their audit trail — the CareOS-global identity.

**Why this is not a seventh `Role`.** Every role in `careos.modules.agency.models.Role` is
carried on `app_user`, which is a tenant-scoped table: it has an `agency_id`, it is covered
by `app_user_tenant_isolation`, and every token minted for one of those users carries a
tenant that `careos.db.session` pins onto the transaction. A CareOS operator has no agency.
Adding them as a role would have meant one of three things, and all three are worse than a
second table:

1. Giving the operator a *real* `agency_id`, which makes them a member of one tenant and
   answers nothing about the other four hundred.
2. Making `app_user.agency_id` nullable, which removes the NOT NULL that
   `04_Data_Model_and_Schema.md` Section 1 relies on and turns every RLS policy comparing
   `agency_id` into one with a NULL case to reason about.
3. Adding a bypass branch to the tenant policies — `USING (agency_id = ... OR
   current_role_is_platform())` — which is the one change that would make a cross-tenant
   leak reachable from an ordinary request, because from then on the policy would have a
   true branch that does not mention the tenant.

The isolation guarantee in `08_Security_Architecture.md` Section 2 is that a handler which
forgets to filter still cannot read another tenant's rows. That holds only while the
tenant predicate has no escape hatch, so the escape hatch is a different principal, a
different database role, a different connection pool, and a different set of grants.

**What an operator may see** is decided by grants, not by handler discipline. The
`careos_platform` database role holds `SELECT` on exactly one view — `platform_agency_health`,
which is `count(*)` and status columns per agency — plus a column-scoped grant on `agency`
for suspension. It holds no grant of any kind on `client`, `caregiver`, `scheduled_visit`,
`evv_record`, `credential`, `applicant_profile`, or `audit_log` reads. A platform handler
that tried to select a client row gets `permission denied for table client`, which is a
property of the database rather than a promise about the code.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from careos.db.base import Base, PrimaryKeyMixin, TimestampMixin


class PlatformRole(enum.StrEnum):
    """What a CareOS operator may do. Two, and the split is read versus act.

    `platform_support` exists so that the people who look at the fleet all day — the ones
    answering "is this agency's EVV stuck?" — are not also the people who can take an agency
    offline. `08_Security_Architecture.md` Section 1's minimum-necessary rule applies to
    CareOS's own staff at least as strongly as to an agency's.
    """

    #: May read the fleet and suspend, reinstate, and manage operators.
    platform_admin = "platform_admin"
    #: May read the fleet and nothing else. Enforced centrally on HTTP method, the same way
    #: the tenant-side `auditor` role is.
    platform_support = "platform_support"


class PlatformOperatorStatus(enum.StrEnum):
    active = "active"
    suspended = "suspended"


#: Read-only platform roles. Mutating methods are refused centrally in
#: `careos.core.rbac.requires_platform`, so a route cannot forget.
PLATFORM_READ_ONLY_ROLES: frozenset[PlatformRole] = frozenset({PlatformRole.platform_support})


class PlatformOperator(Base, PrimaryKeyMixin, TimestampMixin):
    """A CareOS employee with cross-tenant operational visibility.

    Global by construction: no `agency_id`, declared in `careos.db.models.GLOBAL_TABLES`, no
    RLS policy. That is the point — an operator belongs to CareOS, not to a tenant.

    Structurally close to `AppUser` on purpose: the same Argon2 password column, the same
    `auth_provider_id` seam for the managed OIDC provider that
    `08_Security_Architecture.md` Section 1 calls for, the same encrypted TOTP secret, the
    same single-use counter, the same hashed recovery codes, and the same session-revocation
    watermark. Sharing the shape means the MFA and offboarding mechanisms that were built and
    tested once are reused rather than re-implemented, which is the failure mode of a second
    identity table.
    """

    __tablename__ = "platform_operator"
    __table_args__ = (UniqueConstraint("email", name="uq_platform_operator_email"),)

    email: Mapped[str] = mapped_column(Text, nullable=False)
    #: Shown in the console beside an action, so an audit row reads as a person rather than
    #: as a UUID. Not PHI and not an agency's data.
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[PlatformRole] = mapped_column(
        SAEnum(PlatformRole, name="platform_role"), nullable=False
    )
    #: The same seam as `app_user.auth_provider_id`. When the managed identity provider
    #: lands, operators move to it with everyone else and the password column below goes.
    auth_provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PlatformOperatorStatus] = mapped_column(
        SAEnum(PlatformOperatorStatus, name="platform_operator_status"),
        nullable=False,
        default=PlatformOperatorStatus.active,
    )
    #: **Unconditional**, unlike the tenant side. `CAREOS_MFA_REQUIRED` governs whether an
    #: unenrolled privileged *agency* user is confined to the enrolment endpoints, and it is
    #: off by default because switching it on turns every existing session into a prompt.
    #: There is no equivalent flag here: the most privileged principal in the system does not
    #: get a configuration setting that can leave it on one factor.
    mfa_enrolled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Encrypted with the same field key as DOB, tax ID, and the tenant-side TOTP secret.
    mfa_secret_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    #: Last accepted TOTP counter, so a code cannot be presented twice inside its window.
    mfa_last_counter: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: Argon2 hashes of ten single-use recovery codes.
    mfa_recovery_hashes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    #: Revocation watermark. Any token issued at or before this instant is refused, which is
    #: what makes offboarding a CareOS employee take effect on their next request rather than
    #: at the end of a fifteen-minute TTL.
    sessions_revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disabled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformAuditAction(enum.StrEnum):
    """Auditable platform actions. Closed set, for the same reason `AuditAction` is."""

    operator_login_succeeded = "platform.login_succeeded"
    operator_login_failed = "platform.login_failed"
    operator_created = "platform.operator_created"
    operator_disabled = "platform.operator_disabled"
    operator_enabled = "platform.operator_enabled"
    operator_mfa_enrolment_started = "platform.operator_mfa_enrolment_started"
    operator_mfa_enrolled = "platform.operator_mfa_enrolled"
    #: The fleet list. Audited even though it carries only counts: "who looked at the
    #: customer list, and when" is a question a SOC 2 auditor asks, and an access log that
    #: only records writes cannot answer it.
    fleet_viewed = "platform.fleet_viewed"
    #: One agency's operational detail.
    agency_health_viewed = "platform.agency_health_viewed"
    agency_suspended = "platform.agency_suspended"
    agency_reinstated = "platform.agency_reinstated"


class PlatformAuditLog(Base, PrimaryKeyMixin):
    """Append-only record of everything a platform operator did or looked at.

    A second table rather than rows in `audit_log`, for three reasons:

    * `audit_log.agency_id` is NOT NULL and `audit_log.actor_user_id` references `app_user`.
      A platform operator is neither, and loosening either column would weaken the tenant
      trail to accommodate a principal that is not part of it.
    * `audit_log` is tenant-scoped and readable by an agency's own auditor. The fleet-wide
      actions recorded here name other agencies; putting them in one tenant's trail would
      itself be a cross-tenant disclosure.
    * A platform read has no tenant at all when it is the fleet list.

    Actions that *affect* a specific agency are written to **both**: here, and into that
    agency's own `audit_log`, so the agency can see in its own records that CareOS suspended
    it and why. See `careos.modules.platform.service.suspend_agency`.

    Append-only by grant, like `audit_log`: `careos_platform` holds SELECT and INSERT and
    nothing else.
    """

    __tablename__ = "platform_audit_log"
    __table_args__ = (
        Index("ix_platform_audit_log_occurred", "occurred_at"),
        Index("ix_platform_audit_log_subject_agency", "subject_agency_id", "occurred_at"),
    )

    #: Null only for a login attempt against an address with no operator account — there is
    #: no actor to attribute it to, and inventing one would be a fiction in an audit trail.
    actor_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("platform_operator.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    #: The agency this action concerned, when it concerned one. Deliberately not named
    #: `agency_id`: that name is reserved for the tenant key, and `careos.db.models` derives
    #: the tenant-table list from the presence of that exact column.
    subject_agency_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agency.id", ondelete="RESTRICT"), nullable=True
    )
    #: The operator this action concerned, for operator management.
    subject_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("platform_operator.id", ondelete="RESTRICT"), nullable=True
    )
    #: Reasons, counts, and before/after status. Never tenant PHI — nothing reachable by this
    #: role is PHI, which is the point of the grant model rather than a rule about payloads.
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


#: The read-only view the platform console is built on, and the only cross-tenant read the
#: `careos_platform` role is granted.
#:
#: One row per agency, every column either an identifier the agency chose to register under,
#: a status, a `count(*)`, or a timestamp. It is created and owned in migration
#: `0013_platform_operations`; naming it here keeps the Python and the SQL from drifting
#: silently, and `tests/test_platform_console.py` asserts the two agree.
PLATFORM_HEALTH_VIEW = "platform_agency_health"

#: Columns the view exposes, in order. Asserted against the database in the test suite, so a
#: column added to the migration and not here — or the reverse — fails rather than producing
#: a console field that is always empty.
PLATFORM_HEALTH_COLUMNS: tuple[str, ...] = (
    "agency_id",
    "legal_name",
    "status",
    "suspended_at",
    "suspended_reason",
    "service_states",
    "service_lines",
    "created_at",
    "users_total",
    "users_active",
    "owner_admins_active",
    "users_missing_mfa",
    "caregivers_active",
    "clients_active",
    "visits_next_7d",
    "visits_unfilled_next_7d",
    "evv_pending",
    "evv_transmitted",
    "evv_acknowledged",
    "evv_rejected",
    "evv_oldest_pending_at",
    "exceptions_open_critical",
    "exceptions_open_warning",
    "exceptions_open_info",
    "credentials_expired",
    "credentials_expiring_30d",
    "last_user_login_at",
)
