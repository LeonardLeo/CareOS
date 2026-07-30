"""Request and response models for the v1 API.

Shapes follow `05_API_Specification.md`. Two conventions worth stating once:

* Timestamps are ISO 8601 UTC on the wire (Section 1).
* No request model accepts an `agency_id`. The tenant is derived from the token, and
  accepting it as input — even for convenience — would create exactly the client-supplied
  tenant-scoping path Section 1 prohibits.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from careos.modules.agency.models import Role


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth -----------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


# --- Agency & users -------------------------------------------------------------------


class AgencyCreate(BaseModel):
    legal_name: str = Field(min_length=1, max_length=300)
    tax_id: str | None = None
    #: Two-letter state codes. These select the EVV adapter and compliance rule set for the
    #: agency (US-1.1.1), so they are validated rather than accepted as free text.
    service_states: list[str] = Field(min_length=1)
    service_lines: list[Literal["home_care", "home_health", "hospice"]] = Field(min_length=1)
    accepted_payer_types: list[
        Literal["medicaid_waiver", "medicare_advantage", "private_pay", "other"]
    ] = Field(min_length=1)
    owner_email: EmailStr
    owner_password: str = Field(min_length=12)

    @field_validator("service_states")
    @classmethod
    def _upper_two_letter(cls, value: list[str]) -> list[str]:
        normalized = []
        for state in value:
            if len(state) != 2 or not state.isalpha():
                raise ValueError(f"{state!r} is not a two-letter state code")
            normalized.append(state.upper())
        return normalized


class AgencyOut(ORMModel):
    id: uuid.UUID
    legal_name: str
    service_states: list[str]
    service_lines: list[str]
    accepted_payer_types: list[str]
    parent_org_id: uuid.UUID | None
    created_at: datetime


class AgencyUpdate(BaseModel):
    legal_name: str | None = None
    service_states: list[str] | None = None
    service_lines: list[str] | None = None
    accepted_payer_types: list[str] | None = None


class UserInvite(BaseModel):
    email: EmailStr
    role: Role
    phone: str | None = None
    #: Provisional: set at invite time so the account is usable before the managed identity
    #: provider is wired up. Removed with the local password path.
    initial_password: str = Field(min_length=12)


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    role: Role
    status: str
    mfa_enrolled: bool
    created_at: datetime
    #: When this user's sessions were last cut off, or None. Returned so an administrator can
    #: see that an offboarding actually took effect rather than having to trust that it did.
    sessions_revoked_at: datetime | None = None


class RoleChange(BaseModel):
    role: Role


class RevokeSessions(BaseModel):
    """Why access is being cut off.

    Required rather than optional, and recorded in the audit log. Revocation is the action an
    agency will need to evidence during an audit — "we removed access when this caregiver left"
    is a claim, and a reason attached to a timestamp is what supports it.
    """

    reason: str = Field(min_length=3, max_length=500)


class TerminateCaregiver(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


# --- Clients & care plans -------------------------------------------------------------


class ClientCreate(BaseModel):
    legal_name: str = Field(min_length=1, max_length=300)
    dob: date | None = None
    address: str | None = None
    geo_lat: float | None = Field(default=None, ge=-90, le=90)
    geo_lng: float | None = Field(default=None, ge=-180, le=180)
    service_state: str = Field(min_length=2, max_length=2)
    primary_payer_type: Literal["medicaid_waiver", "medicare_advantage", "private_pay", "other"]

    @field_validator("service_state")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


class ClientOut(ORMModel):
    id: uuid.UUID
    legal_name: str
    service_state: str
    primary_payer_type: str
    status: str
    created_at: datetime


class CarePlanCreate(BaseModel):
    authorized_tasks: list[dict[str, Any]] = Field(default_factory=list)
    #: iCalendar RRULE plus the time of day visits start.
    visit_frequency_rule: dict[str, Any]
    effective_start: date
    effective_end: date | None = None
    clinical_supervisor_id: uuid.UUID | None = None
    default_service_type_code: str | None = None


class CarePlanOut(ORMModel):
    id: uuid.UUID
    client_id: uuid.UUID
    authorized_tasks: list[Any]
    # The recurrence rule decides which visits generation produces, so it belongs in the
    # response: without it a scheduler about to generate a month of work cannot see the
    # pattern that work will follow, and with more than one plan cannot tell them apart.
    visit_frequency_rule: dict[str, Any]
    effective_start: date
    effective_end: date | None
    default_service_type_code: str | None


class GenerateVisitsRequest(BaseModel):
    window_start: date
    window_end: date
    duration_minutes: int = Field(default=60, gt=0, le=24 * 60)

    @field_validator("window_end")
    @classmethod
    def _end_after_start(cls, value: date, info) -> date:
        start = info.data.get("window_start")
        if start and value < start:
            raise ValueError("window_end must not precede window_start")
        return value


# --- Visits & EVV ---------------------------------------------------------------------


class VisitOut(ORMModel):
    id: uuid.UUID
    care_plan_id: uuid.UUID
    caregiver_id: uuid.UUID | None
    scheduled_start: datetime
    scheduled_end: datetime
    status: str
    service_type_code: str | None
    service_state: str | None
    payer_type: str | None


class AssignRequest(BaseModel):
    caregiver_id: uuid.UUID


class GeoPoint(BaseModel):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lng: Annotated[float, Field(ge=-180, le=180)]


class ClockInRequest(BaseModel):
    timestamp: datetime
    capture_method: Literal["mobile_gps", "telephony", "manual_exception"] = "mobile_gps"
    geo: GeoPoint | None = None
    #: Generated on-device before connectivity exists, so a replayed offline action is
    #: recognised as the same clock-in rather than a second one
    #: (`05_API_Specification.md` Section 4).
    client_local_uuid: str | None = None


class ClockOutRequest(BaseModel):
    timestamp: datetime
    geo: GeoPoint | None = None
    client_local_uuid: str | None = None


class EVVStatusOut(ORMModel):
    id: uuid.UUID
    scheduled_visit_id: uuid.UUID
    clock_in_time: datetime | None
    clock_out_time: datetime | None
    capture_method: str
    transmission_status: str
    transmission_attempts: int
    aggregator_key: str | None
    #: True only once the state aggregator has acknowledged — not merely received — the
    #: record (`07_Integration_Specifications.md` Section 2).
    is_compliant: bool


class MyVisitClientOut(BaseModel):
    """The client detail a caregiver needs in order to perform an assigned visit.

    Deliberately narrower than `ClientOut`. HIPAA's minimum-necessary rule
    (`08_Security_Architecture.md` Section 1) governs what this surface may carry: a caregiver
    needs the name to greet the right person, the address to get there, and coordinates
    because the geofence rule compares clock-in location against them. Date of birth is not
    required to deliver a personal-care visit, so it is not returned here even though the
    record holds it.
    """

    id: uuid.UUID
    legal_name: str
    address: str | None
    geo_lat: float | None
    geo_lng: float | None


class MyVisitOut(BaseModel):
    """One of the caller's own assigned visits, with everything the app needs offline.

    The EVV state travels with the visit so the app can restore an in-progress visit after a
    reload or a reinstall. Without it, a caregiver who clocked in and then lost the tab would
    have no way to tell whether their clock-in exists, which is the one question this surface
    must always be able to answer.
    """

    id: uuid.UUID
    care_plan_id: uuid.UUID
    scheduled_start: datetime
    scheduled_end: datetime
    status: str
    service_type_code: str | None
    service_state: str | None
    client: MyVisitClientOut
    authorized_tasks: list[Any]
    clock_in_time: datetime | None
    clock_out_time: datetime | None


class ComplianceFindingOut(BaseModel):
    rule_key: str
    severity: str
    message: str
    details: dict[str, Any]


class ClockOutResponse(BaseModel):
    evv: EVVStatusOut
    compliance_findings: list[ComplianceFindingOut]


# --- Caregivers -----------------------------------------------------------------------


class CaregiverCreate(BaseModel):
    legal_name: str = Field(min_length=1, max_length=300)
    dob: date | None = None
    address: str | None = None
    geo_lat: float | None = Field(default=None, ge=-90, le=90)
    geo_lng: float | None = Field(default=None, ge=-180, le=180)
    app_user_id: uuid.UUID | None = None


class CaregiverOut(ORMModel):
    id: uuid.UUID
    legal_name: str
    employment_status: str
    exclusion_check_status: str
    exclusion_checked_at: datetime | None
    created_at: datetime


class ExclusionCheckResult(BaseModel):
    """Result of an OIG LEIE / GSA SAM screening.

    Recorded through its own endpoint rather than a general caregiver PATCH: this field
    gates Medicaid-billed scheduling, so every change to it is a discrete, audited event.
    """

    status: Literal["cleared", "flagged"]
    vendor_key: str
    vendor_reference: str | None = None


# --- Pagination -----------------------------------------------------------------------


class Page(BaseModel):
    page: int
    page_size: int
    total: int


class VisitPage(BaseModel):
    items: list[VisitOut]
    page: Page


# --- Recruiting (Epic 1.2) --------------------------------------------------------------


class JobPostingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    required_credential_types: list[str] = Field(default_factory=list)
    service_state: str | None = Field(default=None, min_length=2, max_length=2)


class JobPostingOut(ORMModel):
    id: uuid.UUID
    title: str
    description: str | None
    required_credential_types: list[Any]
    service_state: str | None
    status: str
    created_at: datetime


class ApplicantCreate(BaseModel):
    """Normalized applicant intake.

    Deliberately has no field for date of birth, address, or any demographic attribute.
    The ranking model must not receive protected-class attributes or their proxies
    (`06_Compliance_and_Regulatory_Requirements.md` Section 5), and the most reliable way to
    guarantee that is not to collect them into the hiring record at all.
    """

    job_posting_id: uuid.UUID | None = None
    source: str = "direct"
    full_name: str = Field(min_length=1, max_length=300)
    email: EmailStr | None = None
    phone: str | None = None
    claimed_credentials: list[str] = Field(default_factory=list)
    availability: dict[str, Any] = Field(default_factory=dict)
    geo_lat: float | None = Field(default=None, ge=-90, le=90)
    geo_lng: float | None = Field(default=None, ge=-180, le=180)


class RankingFactorOut(BaseModel):
    factor: str
    weight: float
    rationale: str


class ApplicantOut(ORMModel):
    id: uuid.UUID
    job_posting_id: uuid.UUID | None
    source: str
    full_name: str
    email: str | None
    phone: str | None
    claimed_credentials: list[Any]
    pipeline_stage: str
    ranking_score: float | None
    #: Never empty when `ranking_score` is set — enforced in the database as well.
    ranking_factors: list[Any]
    ranking_model_version: str | None
    created_at: datetime


class StageChange(BaseModel):
    stage: Literal["screened", "offer", "hired", "rejected"]


class FunnelStageOut(BaseModel):
    stage: str
    count: int
    conversion_from_previous: float | None


# --- Shift matching (Epic 1.4) ----------------------------------------------------------


class CaregiverSuggestionOut(BaseModel):
    caregiver_id: uuid.UUID
    caregiver_name: str
    score: float
    #: Inline reasoning. `09_UX_Design_and_User_Flows.md` principle 4 requires every AI
    #: suggestion to show why, never a bare number.
    factors: list[RankingFactorOut]
    warnings: list[str]


# --- Credentialing (Epic 1.3) -----------------------------------------------------------


class CredentialCreate(BaseModel):
    credential_type: str
    issuing_body: str | None = None
    credential_number: str | None = None
    issue_date: date | None = None
    expiration_date: date | None = None
    verification_status: Literal["pending", "verified", "expired", "rejected"] = "pending"


class CredentialOut(ORMModel):
    id: uuid.UUID
    caregiver_id: uuid.UUID
    credential_type: str
    issuing_body: str | None
    issue_date: date | None
    expiration_date: date | None
    verification_status: str


class ExpiringCredentialOut(BaseModel):
    credential_id: uuid.UUID
    caregiver_id: uuid.UUID
    caregiver_name: str
    credential_type: str
    expiration_date: date
    days_until_expiry: int
    bucket: int
    already_expired: bool


# --- Compliance reviews (06_Compliance Section 9) ----------------------------------------


class ReviewStatusOut(BaseModel):
    review_type: str
    last_performed_on: date | None
    last_outcome: str | None
    next_due_on: date | None
    is_overdue: bool
    #: Distinct from overdue, and more serious: this review has never been run at all.
    never_performed: bool


# --- Compliance exception queue (US-1.4.6) ------------------------------------------------


class ComplianceExceptionOut(ORMModel):
    id: uuid.UUID
    rule_key: str
    severity: str
    entity_type: str
    entity_id: uuid.UUID
    message: str
    details: dict[str, Any]
    created_at: datetime
    resolved_at: datetime | None


class ExceptionSummaryOut(BaseModel):
    total_open: int
    by_severity: dict[str, int]


class ResolveException(BaseModel):
    note: str | None = None
