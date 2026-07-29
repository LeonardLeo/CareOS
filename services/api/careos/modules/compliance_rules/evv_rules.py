"""Phase 1 EVV and scheduling compliance rules (PRD US-1.4.6).

These are the first consumers of the generic engine. They deliberately read from a plain
context dict rather than ORM objects, so the same rules can later run over a claim line in
Phase 3 without dragging the scheduling models into the billing module.

Importing this module registers the rules. `careos.modules.compliance_rules` does that on
package import so no caller has to remember to.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from careos.modules.compliance_rules.engine import (
    Finding,
    Rule,
    RuleConfig,
    Severity,
    engine,
)

SUBJECT_VISIT = "visit"

#: Default radius within which a clock-in is considered to be at the client's home.
#: A default, not a constant — rural service areas and imprecise geocoding both push this
#: up, and an agency can raise it via RuleConfig without a deploy.
DEFAULT_GEOFENCE_METERS = 150.0

_EARTH_RADIUS_M = 6_371_000.0


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _missing_clock_times(context: dict[str, Any], _config: RuleConfig) -> Iterable[Finding]:
    """A completed visit with no clock-in or clock-out cannot produce a compliant EVV record."""
    if context.get("visit_status") != "completed":
        return []
    findings = []
    for field_name, label in (("clock_in_time", "clock-in"), ("clock_out_time", "clock-out")):
        if context.get(field_name) is None:
            findings.append(
                Finding(
                    rule_key="evv.missing_clock_time",
                    severity=Severity.critical,
                    message=f"Visit was completed without a recorded {label} time",
                    entity_type=SUBJECT_VISIT,
                    entity_id=context.get("entity_id"),
                    details={"missing": field_name},
                )
            )
    return findings


def _coordinate(value: Any) -> float | None:
    """Coerce a context value to a float, preserving None.

    Coordinates arrive as `Decimal` from Postgres `NUMERIC` columns, or as plain floats from
    a hand-built context in tests, or absent entirely.
    """
    return None if value is None else float(value)


def _outside_geofence(context: dict[str, Any], config: RuleConfig) -> Iterable[Finding]:
    """Clock-in coordinates too far from the client's address.

    Skipped entirely for telephony and manual-exception capture, which have no coordinates
    by design — flagging those would train schedulers to ignore the alert.
    """
    if context.get("capture_method") != "mobile_gps":
        return []
    clock_lat = _coordinate(context.get("clock_in_lat"))
    clock_lng = _coordinate(context.get("clock_in_lng"))
    client_lat = _coordinate(context.get("client_lat"))
    client_lng = _coordinate(context.get("client_lng"))
    # Either side may be missing — a manual-exception clock-in has no fix, and a client
    # record may not be geocoded yet. Without both, there is nothing to compare.
    if clock_lat is None or clock_lng is None or client_lat is None or client_lng is None:
        return []

    radius = float(config.params.get("geofence_meters", DEFAULT_GEOFENCE_METERS))
    distance = haversine_meters(clock_lat, clock_lng, client_lat, client_lng)
    if distance <= radius:
        return []
    return [
        Finding(
            rule_key="evv.outside_geofence",
            severity=Severity.warning,
            message=(
                f"Clock-in was {distance:.0f}m from the client's registered address "
                f"(threshold {radius:.0f}m)"
            ),
            entity_type=SUBJECT_VISIT,
            entity_id=context.get("entity_id"),
            details={"distance_meters": round(distance, 1), "threshold_meters": radius},
        )
    ]


def _missing_service_code(context: dict[str, Any], _config: RuleConfig) -> Iterable[Finding]:
    """A visit with no service code cannot be matched to an authorized service.

    Phase 1 does not bill, but a visit recorded without this is unbillable in Phase 3 and
    unfixable by then — `03_Technical_Architecture.md` Section 6 calls out the retrofit cost
    directly. Flagging it now is the whole reason the column exists in Phase 1.
    """
    if context.get("service_type_code"):
        return []
    return [
        Finding(
            rule_key="evv.missing_service_code",
            severity=Severity.warning,
            message="Visit has no service type code, so it cannot be matched to an "
            "authorized service or billed later",
            entity_type=SUBJECT_VISIT,
            entity_id=context.get("entity_id"),
        )
    ]


def _transmission_rejected(context: dict[str, Any], _config: RuleConfig) -> Iterable[Finding]:
    """Rejected or unacknowledged transmission — the visit is not yet compliant."""
    status = context.get("transmission_status")
    if status == "rejected":
        return [
            Finding(
                rule_key="evv.transmission_rejected",
                severity=Severity.critical,
                message="The state aggregator rejected this visit's EVV record",
                entity_type=SUBJECT_VISIT,
                entity_id=context.get("entity_id"),
                details={"aggregator_response": context.get("aggregator_response") or {}},
            )
        ]
    if context.get("visit_status") == "completed" and status in {"pending", "transmitted"}:
        return [
            Finding(
                rule_key="evv.transmission_unacknowledged",
                severity=Severity.warning,
                message=(
                    "Visit is complete but its EVV record has not been acknowledged by the "
                    "state aggregator"
                ),
                entity_type=SUBJECT_VISIT,
                entity_id=context.get("entity_id"),
                details={"transmission_status": status},
            )
        ]
    return []


def _expired_credential(context: dict[str, Any], _config: RuleConfig) -> Iterable[Finding]:
    """Caregiver worked a visit holding a credential that had expired by the service date."""
    service_date = context.get("service_date")
    if not isinstance(service_date, date):
        return []
    findings = []
    for credential in context.get("caregiver_credentials", []) or []:
        expiry = credential.get("expiration_date")
        if isinstance(expiry, datetime):
            expiry = expiry.date()
        if isinstance(expiry, date) and expiry < service_date:
            findings.append(
                Finding(
                    rule_key="credentialing.expired_at_visit",
                    severity=Severity.critical,
                    message=(
                        f"Caregiver's {credential.get('credential_type')} expired on {expiry}, "
                        f"before the {service_date} service date"
                    ),
                    entity_type=SUBJECT_VISIT,
                    entity_id=context.get("entity_id"),
                    details={
                        "credential_type": credential.get("credential_type"),
                        "expiration_date": str(expiry),
                    },
                )
            )
    return findings


def _exclusion_not_cleared(context: dict[str, Any], _config: RuleConfig) -> Iterable[Finding]:
    """Caregiver on a Medicaid/Medicare-billed visit without a cleared exclusion check.

    This is the reporting half of the hard gate in PRD US-1.3.2. The gate itself lives in
    `careos.modules.scheduling.service.assert_assignable` and refuses the assignment
    outright; this rule catches records that predate the gate or were created by an import.
    """
    if context.get("exclusion_check_status") == "cleared":
        return []
    if context.get("payer_type") not in {"medicaid_waiver", "medicare_advantage"}:
        return []
    return [
        Finding(
            rule_key="credentialing.exclusion_not_cleared",
            severity=Severity.critical,
            message=(
                "Caregiver is assigned to a publicly-funded visit without a cleared "
                "OIG/GSA exclusion check"
            ),
            entity_type=SUBJECT_VISIT,
            entity_id=context.get("entity_id"),
            details={"exclusion_check_status": context.get("exclusion_check_status")},
            blocking=True,
        )
    ]


def register_phase1_rules() -> None:
    """Idempotent registration, so repeated imports in tests do not raise."""
    if engine.rules_for(SUBJECT_VISIT):
        return
    for rule in (
        Rule(
            key="evv.missing_clock_time",
            subject=SUBJECT_VISIT,
            default_severity=Severity.critical,
            description="Completed visit is missing a clock-in or clock-out time",
            evaluate=_missing_clock_times,
        ),
        Rule(
            key="evv.outside_geofence",
            subject=SUBJECT_VISIT,
            default_severity=Severity.warning,
            description="GPS clock-in occurred outside the client's geofence",
            evaluate=_outside_geofence,
        ),
        Rule(
            key="evv.missing_service_code",
            subject=SUBJECT_VISIT,
            default_severity=Severity.warning,
            description="Visit has no billing-relevant service type code",
            evaluate=_missing_service_code,
        ),
        Rule(
            key="evv.transmission_status",
            subject=SUBJECT_VISIT,
            default_severity=Severity.critical,
            description="EVV record was rejected or is not yet acknowledged",
            evaluate=_transmission_rejected,
        ),
        Rule(
            key="credentialing.expired_at_visit",
            subject=SUBJECT_VISIT,
            default_severity=Severity.critical,
            description="Caregiver credential had expired by the visit's service date",
            evaluate=_expired_credential,
        ),
        Rule(
            key="credentialing.exclusion_not_cleared",
            subject=SUBJECT_VISIT,
            default_severity=Severity.critical,
            description="Caregiver lacks a cleared exclusion check for a publicly-funded visit",
            evaluate=_exclusion_not_cleared,
            blocking=True,
        ),
    ):
        engine.register(rule)
