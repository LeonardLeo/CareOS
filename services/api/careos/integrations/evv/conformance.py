"""The shaped records a state's EVV integration has to be proved against.

`13_Phase_1_Launch_Plan.md` 5.1 names six: a normal visit, a manual exception, a telephony
capture, a visit crossing midnight, a cancelled visit, and a visit with a corrected clock-out.
Four of those this system can express today. Two it cannot, and that is recorded here rather
than approximated — see `UNEXPRESSIBLE` below.

The point of a fixture set is not that the shapes are interesting. It is that once a state's
field map has been agreed with a vendor, nothing may change it by accident. A map lives in a
dict of a dozen strings; renaming one is a two-character edit that no test would otherwise
notice, and the consequence surfaces months later as a rejected claim for visits that have
already been delivered and paid for.

So `scenarios()` builds deterministic payloads — fixed UUIDs, fixed timestamps, no clock —
and `tests/test_evv_conformance.py` snapshots what each adapter puts on the wire for them.
Regenerate deliberately:

    python -m careos.scripts.record_evv_conformance

A diff in that file is the review question "did we mean to change what New York receives?",
which is the question that would otherwise never get asked.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from careos.integrations.evv.base import EVVPayload

#: Fixed identifiers, so a regenerated fixture differs only where behaviour differs. Random
#: UUIDs would make every regeneration a full-file diff, and a full-file diff is one nobody
#: reads — which would defeat the entire mechanism.
AGENCY_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
CLIENT_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
CAREGIVER_ID = uuid.UUID("00000000-0000-4000-8000-000000000003")

#: A Wednesday, chosen so the midnight-crossing case lands on a weekday in every US timezone.
BASE_DAY = datetime(2026, 3, 11, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Scenario:
    """One shaped record, and why a vendor has to be shown it."""

    key: str
    why: str
    payload: EVVPayload


#: The two scenarios from the plan that this system has no way to express, and why.
#:
#: Both are message *types* rather than payload variations: a cancellation withdraws a visit
#: already transmitted, and a correction supersedes one. `EVVTransmissionAdapter` has a single
#: `submit`, so there is nothing to shape. Inventing a `message_type` field and guessing at
#: each vendor's vocabulary would produce fixtures that look like coverage and pin nothing.
#:
#: These are the first two questions for the New York sandbox contact, and the adapter
#: interface grows a method once the answers are known.
UNEXPRESSIBLE: dict[str, str] = {
    "cancelled_visit": (
        "Withdrawing an already-transmitted visit is a separate message type, and the adapter "
        "interface has only submit. Ask the aggregator how a cancellation is expressed."
    ),
    "corrected_clock_out": (
        "Superseding a transmitted visit needs a reference to the original and a reason code. "
        "Neither is modelled. Ask the aggregator what a correction carries."
    ),
}


# The location shapes below are copied from `scheduling.service.build_evv_payload`, not
# invented. A fixture that pins a shape the real clock-in path never produces would pass
# forever while proving nothing about what an aggregator actually receives — which is the
# specific way a snapshot test becomes decoration.
def _payload(
    *,
    visit_id: str,
    service_start: datetime,
    service_end: datetime,
    capture_method: str,
    location: dict[str, Any],
    service_type_code: str = "T1019",
    extra: dict[str, Any] | None = None,
) -> EVVPayload:
    return EVVPayload(
        visit_id=uuid.UUID(visit_id),
        agency_id=AGENCY_ID,
        state_code="NY",
        service_type_code=service_type_code,
        client_id=CLIENT_ID,
        client_name="Eleanor Whitfield",
        service_date=service_start.date().isoformat(),
        location=location,
        caregiver_id=CAREGIVER_ID,
        caregiver_name="Ama Boateng",
        service_start=service_start,
        service_end=service_end,
        capture_method=capture_method,
        extra=extra or {},
    )


def scenarios() -> list[Scenario]:
    """Every shaped record, in a stable order.

    Ordered so the fixture file reads from ordinary to awkward. A reviewer looking at a diff
    should hit the normal case first and know immediately whether the change is broad or
    confined to an edge.
    """
    return [
        Scenario(
            key="normal_mobile_gps",
            why=(
                "The ordinary case, and the baseline every other scenario is a deviation "
                "from. If this one is wrong, nothing else matters."
            ),
            payload=_payload(
                visit_id="00000000-0000-4000-8000-000000000010",
                service_start=BASE_DAY.replace(hour=9),
                service_end=BASE_DAY.replace(hour=11),
                capture_method="mobile_gps",
                location={
                    "coordinates": {"lat": 40.6461, "lng": -74.0175},
                    "capture_method": "mobile_gps",
                },
            ),
        ),
        Scenario(
            key="telephony_no_coordinates",
            why=(
                "A caregiver with no smartphone clocks in from the client's landline, so "
                "there are no coordinates at all. `06_Compliance...` Section 1 accepts "
                "telephony as a capture method; a map that requires a latitude will reject "
                "every visit from this workforce, and that workforce is not small."
            ),
            payload=_payload(
                visit_id="00000000-0000-4000-8000-000000000011",
                service_start=BASE_DAY.replace(hour=13),
                service_end=BASE_DAY.replace(hour=15),
                capture_method="telephony",
                location={
                    "absence_reason": "telephony_capture",
                    "capture_method": "telephony",
                },
            ),
        ),
        Scenario(
            key="manual_exception",
            why=(
                "The phone was dead and a coordinator entered the visit afterwards. Every "
                "state treats manual entry as auditable rather than forbidden, and the "
                "reason has to survive the mapping — a manual visit transmitted as though "
                "it were GPS-captured is a misrepresentation, not a rounding error."
            ),
            payload=_payload(
                visit_id="00000000-0000-4000-8000-000000000012",
                service_start=BASE_DAY.replace(hour=8),
                service_end=BASE_DAY.replace(hour=10),
                capture_method="manual_exception",
                location={
                    "absence_reason": "manual_exception",
                    "capture_method": "manual_exception",
                },
            ),
        ),
        Scenario(
            key="crosses_midnight",
            why=(
                "An overnight shift ends on a different calendar day from the one it "
                "started. `date_of_service` is derived from the start, and an aggregator "
                "that reads the end date instead will file the visit against the wrong day "
                "— which surfaces as a duplicate or an unauthorised visit, never as an "
                "error message."
            ),
            payload=_payload(
                visit_id="00000000-0000-4000-8000-000000000013",
                service_start=BASE_DAY.replace(hour=22),
                service_end=BASE_DAY.replace(day=12, hour=6),
                capture_method="mobile_gps",
                location={
                    "coordinates": {"lat": 40.6461, "lng": -74.0175},
                    "capture_method": "mobile_gps",
                },
            ),
        ),
    ]


def wire_bodies() -> dict[str, dict[str, Any]]:
    """Every scenario rendered by every REST adapter, as it would go on the wire.

    Grouped adapter-first so a vendor's whole surface is one contiguous block in the fixture
    file. A reviewer checking a New York change should not have to read past Florida's.
    """
    # Imported here rather than at module scope: the registry imports this module's siblings,
    # and a top-level import would make the fixture recorder part of that cycle.
    from careos.integrations.evv.adapters.rest import (
        HHAeXchangeAdapter,
        SandataAdapter,
        TellusAdapter,
    )

    adapters = [SandataAdapter(), HHAeXchangeAdapter(), TellusAdapter()]
    out: dict[str, dict[str, Any]] = {}
    for adapter in adapters:
        out[adapter.adapter_key] = {
            scenario.key: adapter.build_body(scenario.payload) for scenario in scenarios()
        }
    return out


def fixture_document() -> dict[str, Any]:
    """The full fixture file, including the parts that are deliberately absent."""
    return {
        "_comment": (
            "Generated by `python -m careos.scripts.record_evv_conformance`. A diff here means "
            "the bytes an aggregator receives have changed. Review it as such."
        ),
        "scenarios": {s.key: s.why for s in scenarios()},
        "not_yet_expressible": UNEXPRESSIBLE,
        "requests": wire_bodies(),
        "responses": {
            "_comment": (
                "Empty until a real sandbox run. Recording a fabricated acknowledgement here "
                "would make the conformance test assert that our own guess is stable, which "
                "is worse than asserting nothing."
            )
        },
    }
