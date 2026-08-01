"""Compliance rules engine tests.

The engine is generic by requirement (PRD Section 6), so these cover both the machinery —
which Phase 2 and 3 will reuse — and the Phase 1 EVV rule set built on it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from careos.modules.compliance_rules import engine as phase1_engine
from careos.modules.compliance_rules.engine import (
    Finding,
    Rule,
    RuleConfig,
    RuleEngine,
    Severity,
)
from careos.modules.compliance_rules.evv_rules import (
    SUBJECT_VISIT,
    haversine_meters,
)

# --- Engine machinery -------------------------------------------------------------------


def _always_fires(_context, _config):
    return [
        Finding(
            rule_key="test.always",
            severity=Severity.info,
            message="fired",
            entity_type="thing",
            entity_id=None,
        )
    ]


def test_engine_registers_and_evaluates() -> None:
    engine = RuleEngine()
    engine.register(
        Rule(
            key="test.always",
            subject="thing",
            default_severity=Severity.warning,
            description="test",
            evaluate=_always_fires,
        )
    )
    findings = engine.evaluate("thing", {})
    assert len(findings) == 1
    # The engine, not the rule, applies severity.
    assert findings[0].severity is Severity.warning


def test_duplicate_rule_key_is_rejected() -> None:
    engine = RuleEngine()
    rule = Rule(
        key="dup",
        subject="thing",
        default_severity=Severity.info,
        description="test",
        evaluate=_always_fires,
    )
    engine.register(rule)
    with pytest.raises(ValueError, match="already registered"):
        engine.register(rule)


def test_agency_config_can_disable_a_rule() -> None:
    """US-2.2.3 wants rules configurable without engineering involvement."""
    engine = RuleEngine()
    engine.register(
        Rule(
            key="test.always",
            subject="thing",
            default_severity=Severity.info,
            description="test",
            evaluate=_always_fires,
        )
    )
    findings = engine.evaluate("thing", {}, config={"test.always": RuleConfig(enabled=False)})
    assert findings == []


def test_agency_config_can_escalate_severity() -> None:
    engine = RuleEngine()
    engine.register(
        Rule(
            key="test.always",
            subject="thing",
            default_severity=Severity.info,
            description="test",
            evaluate=_always_fires,
        )
    )
    findings = engine.evaluate(
        "thing", {}, config={"test.always": RuleConfig(severity=Severity.critical)}
    )
    assert findings[0].severity is Severity.critical


def test_a_failing_rule_does_not_suppress_the_others() -> None:
    """A bug in one rule must not blind the agency to every other problem on the record."""

    def _explodes(_context, _config):
        raise RuntimeError("boom")

    engine = RuleEngine()
    engine.register(
        Rule(
            key="test.broken",
            subject="thing",
            default_severity=Severity.info,
            description="broken",
            evaluate=_explodes,
        )
    )
    engine.register(
        Rule(
            key="test.always",
            subject="thing",
            default_severity=Severity.info,
            description="fine",
            evaluate=_always_fires,
        )
    )

    findings = engine.evaluate("thing", {})
    keys = {f.rule_key for f in findings}
    assert "test.always" in keys, "a broken rule suppressed a working one"
    assert "test.broken.evaluation_error" in keys
    error = next(f for f in findings if f.rule_key == "test.broken.evaluation_error")
    assert error.severity is Severity.critical


def test_blocking_findings_are_separable() -> None:
    engine = RuleEngine()
    engine.register(
        Rule(
            key="test.always",
            subject="thing",
            default_severity=Severity.critical,
            description="test",
            evaluate=_always_fires,
            blocking=True,
        )
    )
    findings = engine.evaluate("thing", {})
    assert engine.blocking_findings(findings) == findings


# --- Geo helper -------------------------------------------------------------------------


def test_haversine_matches_a_known_distance() -> None:
    """Empire State Building to Times Square is roughly 1.6 km."""
    metres = haversine_meters(40.7484, -73.9857, 40.7580, -73.9855)
    assert 1000 < metres < 1200


def test_haversine_is_zero_for_identical_points() -> None:
    assert haversine_meters(40.7, -74.0, 40.7, -74.0) == pytest.approx(0.0, abs=1e-6)


# --- Phase 1 EVV rules -------------------------------------------------------------------


def _base_context(**overrides) -> dict:
    context = {
        "entity_id": uuid.uuid4(),
        "visit_status": "completed",
        "service_type_code": "T1019",
        "payer_type": "medicaid_waiver",
        "service_date": date(2026, 7, 29),
        "clock_in_time": datetime(2026, 7, 29, 9, tzinfo=UTC),
        "clock_out_time": datetime(2026, 7, 29, 10, tzinfo=UTC),
        "clock_in_lat": 40.7128,
        "clock_in_lng": -74.0060,
        "capture_method": "mobile_gps",
        "transmission_status": "acknowledged",
        "aggregator_response": {},
        "client_lat": 40.7128,
        "client_lng": -74.0060,
        "exclusion_check_status": "cleared",
        "caregiver_credentials": [],
    }
    context.update(overrides)
    return context


def _keys(context: dict) -> set[str]:
    return {f.rule_key for f in phase1_engine.evaluate(SUBJECT_VISIT, context)}


def test_clean_visit_produces_no_findings() -> None:
    assert _keys(_base_context()) == set()


def test_missing_clock_out_is_flagged() -> None:
    assert "evv.missing_clock_time" in _keys(_base_context(clock_out_time=None))


def test_incomplete_visit_in_progress_is_not_flagged_for_missing_times() -> None:
    """Only completed visits need both times — an in-progress visit legitimately lacks one."""
    context = _base_context(
        visit_status="in_progress", clock_out_time=None, transmission_status="pending"
    )
    assert "evv.missing_clock_time" not in _keys(context)


#: Roughly 5.5 km from the client's registered address in `_base_context` — well outside
#: the 150 m default geofence, and far enough that the assertion is not sensitive to the
#: exact haversine result.
FAR_FROM_CLIENT = {"clock_in_lat": 40.7580, "clock_in_lng": -73.9855}


def test_clock_in_outside_geofence_is_flagged() -> None:
    assert "evv.outside_geofence" in _keys(_base_context(**FAR_FROM_CLIENT))


def test_clock_in_just_inside_geofence_is_not_flagged() -> None:
    """~50 m away, inside the 150 m default — normal GPS drift must not raise an exception."""
    context = _base_context(clock_in_lat=40.71325, clock_in_lng=-74.0060)
    assert "evv.outside_geofence" not in _keys(context)


def test_geofence_threshold_is_configurable() -> None:
    """An agency serving a rural area can widen the radius without a deploy."""
    context = _base_context(**FAR_FROM_CLIENT)
    # Default (150 m) flags this location...
    assert "evv.outside_geofence" in _keys(context)
    # ...and a 10 km radius does not.
    findings = phase1_engine.evaluate(
        SUBJECT_VISIT,
        context,
        config={"evv.outside_geofence": RuleConfig(params={"geofence_meters": 10_000})},
    )
    assert "evv.outside_geofence" not in {f.rule_key for f in findings}


def test_telephony_capture_is_not_geofence_flagged() -> None:
    """Telephony has no coordinates by design; flagging it would train users to ignore alerts."""
    context = _base_context(capture_method="telephony", clock_in_lat=None, clock_in_lng=None)
    assert "evv.outside_geofence" not in _keys(context)


def test_missing_service_code_is_flagged() -> None:
    assert "evv.missing_service_code" in _keys(_base_context(service_type_code=None))


def test_rejected_transmission_is_flagged() -> None:
    assert "evv.transmission_rejected" in _keys(_base_context(transmission_status="rejected"))


def test_unacknowledged_transmission_is_flagged() -> None:
    """Submitted is not compliant — only acknowledged is."""
    assert "evv.transmission_unacknowledged" in _keys(
        _base_context(transmission_status="transmitted")
    )


def test_credential_expired_before_service_date_is_flagged() -> None:
    context = _base_context(
        caregiver_credentials=[{"credential_type": "HHA", "expiration_date": date(2026, 7, 1)}]
    )
    assert "credentialing.expired_at_visit" in _keys(context)


def test_credential_valid_at_service_date_is_not_flagged() -> None:
    context = _base_context(
        caregiver_credentials=[
            {"credential_type": "HHA", "expiration_date": date(2026, 7, 29) + timedelta(days=30)}
        ]
    )
    assert "credentialing.expired_at_visit" not in _keys(context)


def test_uncleared_exclusion_on_medicaid_visit_is_blocking() -> None:
    findings = phase1_engine.evaluate(
        SUBJECT_VISIT, _base_context(exclusion_check_status="not_run")
    )
    blocking = {f.rule_key for f in RuleEngine.blocking_findings(findings)}
    assert "credentialing.exclusion_not_cleared" in blocking


def test_uncleared_exclusion_on_private_pay_is_not_flagged() -> None:
    context = _base_context(exclusion_check_status="not_run", payer_type="private_pay")
    assert "credentialing.exclusion_not_cleared" not in _keys(context)
