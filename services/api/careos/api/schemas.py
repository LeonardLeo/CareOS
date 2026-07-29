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


class RoleChange(BaseModel):
    role: Role


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
