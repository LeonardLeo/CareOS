"""The EVV transmission contract every state adapter implements.

`07_Integration_Specifications.md` Section 1: a vendor's API shape must never leak into
core domain logic. The scheduling module therefore knows only about `EVVPayload` and
`TransmissionResult`; whether the destination is Sandata's REST API, an HHAeXchange
endpoint, or a state-proprietary batch file is entirely the adapter's business.

`EVVPayload` carries exactly the six data elements mandated by Section 12006 of the 21st
Century Cures Act (`06_Compliance_and_Regulatory_Requirements.md` Section 1). They are
modelled as required fields rather than an open dict so that an incomplete transmission
fails here, in our code, rather than as a rejection from the state weeks later.
"""

from __future__ import annotations

import abc
import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class EVVElementError(ValueError):
    """One of the six federally required elements is missing or unusable."""


@dataclass(frozen=True, slots=True)
class EVVPayload:
    """The six required EVV data elements, plus the routing context an adapter needs.

    Field names map to the federal elements as follows:

    1. type of service performed        -> ``service_type_code``
    2. individual receiving the service -> ``client_id`` / ``client_name``
    3. date of the service              -> ``service_date``
    4. location of service delivery     -> ``location`` (coordinates, or the documented
                                           reason they are absent for telephony capture)
    5. individual providing the service -> ``caregiver_id`` / ``caregiver_name``
    6. time service begins and ends     -> ``service_start`` / ``service_end``
    """

    visit_id: uuid.UUID
    agency_id: uuid.UUID
    state_code: str

    service_type_code: str
    client_id: uuid.UUID
    client_name: str
    service_date: str
    location: dict[str, Any]
    caregiver_id: uuid.UUID
    caregiver_name: str
    service_start: datetime
    service_end: datetime

    capture_method: str
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Assert all six elements are present before anything is transmitted."""
        missing = [
            name
            for name in (
                "service_type_code",
                "client_id",
                "client_name",
                "service_date",
                "caregiver_id",
                "caregiver_name",
                "service_start",
                "service_end",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise EVVElementError(f"EVV payload is missing required element(s): {sorted(missing)}")
        # Element 4 is "location of service delivery". Telephony and manual-exception
        # capture legitimately have no coordinates, but the *reason* must be recorded —
        # an empty location with no explanation is not a compliant record.
        if not self.location.get("coordinates") and not self.location.get("absence_reason"):
            raise EVVElementError(
                "EVV payload location must carry coordinates, or an absence_reason "
                "explaining why they are unavailable (e.g. telephony capture)"
            )
        if self.service_end < self.service_start:
            raise EVVElementError("EVV service_end precedes service_start")

    def as_canonical_snapshot(self) -> dict[str, Any]:
        """The immutable record stored on `evv_record.six_element_snapshot`.

        Keyed by the federal element names rather than our column names, so an auditor
        reading it years from now does not have to map our schema onto the regulation.
        """
        return {
            "type_of_service": self.service_type_code,
            "individual_receiving_service": {
                "id": str(self.client_id),
                "name": self.client_name,
            },
            "date_of_service": self.service_date,
            "location_of_service": self.location,
            "individual_providing_service": {
                "id": str(self.caregiver_id),
                "name": self.caregiver_name,
            },
            "service_begin_time": self.service_start.isoformat(),
            "service_end_time": self.service_end.isoformat(),
            "capture_method": self.capture_method,
        }


class TransmissionOutcome(enum.StrEnum):
    accepted = "accepted"
    #: Received but not yet adjudicated. Not compliant yet — see `TransmissionResult`.
    submitted = "submitted"
    rejected = "rejected"
    #: Transport-level failure. Retryable; distinct from a substantive rejection.
    transient_failure = "transient_failure"


@dataclass(frozen=True, slots=True)
class TransmissionResult:
    outcome: TransmissionOutcome
    aggregator_reference: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    @property
    def is_compliant(self) -> bool:
        """True only on acknowledgement.

        `07_Integration_Specifications.md` Section 2: "a visit is not 'compliant' until
        transmission is acknowledged, not merely submitted."
        """
        return self.outcome is TransmissionOutcome.accepted

    @property
    def is_retryable(self) -> bool:
        return self.outcome is TransmissionOutcome.transient_failure


class EVVTransmissionAdapter(abc.ABC):
    """Base class for a state/aggregator adapter."""

    #: Registry key, referenced by `evv_aggregator_ref.adapter_key`.
    adapter_key: str
    #: Human-readable aggregator name, for dashboards and error messages.
    aggregator_name: str

    def __init__(self, *, config: dict[str, Any] | None = None, sandbox: bool = True) -> None:
        self.config = config or {}
        self.sandbox = sandbox

    @abc.abstractmethod
    async def submit(self, payload: EVVPayload) -> TransmissionResult:
        """Transmit one visit's EVV record to the aggregator."""

    def __repr__(self) -> str:
        mode = "sandbox" if self.sandbox else "production"
        return f"<{type(self).__name__} key={self.adapter_key} {mode}>"
