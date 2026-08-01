"""What each aggregator actually receives, pinned.

A state's field map is a dict of a dozen strings. Renaming one is a two-character edit that
nothing else in this repository would notice — not a type checker, not a unit test, not a
reviewer skimming a diff — and the consequence arrives months later as a rejected claim for
visits already delivered and already paid for. `13_Phase_1_Launch_Plan.md` 5.1 puts these
fixtures in the critical path for exactly that reason.

So this file asserts the bytes. When it fails, the question is not "how do I make the test
pass"; it is "did we mean to change what New York receives?". Answering yes means running
`python -m careos.scripts.record_evv_conformance` and reviewing the diff on its own merits.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from careos.integrations.evv.conformance import (
    UNEXPRESSIBLE,
    fixture_document,
    scenarios,
    wire_bodies,
)

FIXTURE = Path(__file__).parent / "fixtures" / "evv_conformance.json"


@pytest.fixture(scope="module")
def recorded() -> dict:
    if not FIXTURE.exists():  # pragma: no cover - the file is committed
        pytest.fail(f"{FIXTURE} is missing. Run `python -m careos.scripts.record_evv_conformance`.")
    return json.loads(FIXTURE.read_text())


def test_the_wire_bodies_match_what_was_recorded(recorded: dict) -> None:
    """The whole point of the file.

    Compared as a whole rather than key by key, so a *new* field appearing in a body fails
    too. A vendor receiving an extra field it does not expect is as much a conformance
    problem as one missing a field it does.
    """
    assert wire_bodies() == recorded["requests"], (
        "The bytes sent to an aggregator have changed. If that was intended, run "
        "`python -m careos.scripts.record_evv_conformance` and review the diff."
    )


def test_every_scenario_is_represented_for_every_adapter(recorded: dict) -> None:
    """A scenario added to the module and not to the fixture is silent coverage loss."""
    expected = {s.key for s in scenarios()}
    for adapter_key, bodies in recorded["requests"].items():
        assert set(bodies) == expected, (
            f"{adapter_key} is missing scenarios: {expected - set(bodies)}"
        )


def test_the_scenarios_are_the_ones_the_launch_plan_asks_for() -> None:
    """Four expressible, two named as not yet expressible. Six accounted for.

    Pinned so that the two gaps cannot quietly disappear from the record. Deleting an entry
    from `UNEXPRESSIBLE` because it looks untidy would remove the only place the system says
    it cannot cancel or correct a transmitted visit.
    """
    accounted = {s.key for s in scenarios()} | set(UNEXPRESSIBLE)
    assert accounted == {
        "normal_mobile_gps",
        "telephony_no_coordinates",
        "manual_exception",
        "crosses_midnight",
        "cancelled_visit",
        "corrected_clock_out",
    }


def test_a_visit_crossing_midnight_is_filed_against_its_start_date() -> None:
    """The failure this scenario exists to catch does not look like an error.

    A visit starting 22:00 and ending 06:00 filed against the *end* date is a visit on a day
    the client may have no authorisation for. The aggregator accepts it and a payer denies it
    later, so nothing in the system ever reports a problem.
    """
    bodies = wire_bodies()
    for adapter_key, per_scenario in bodies.items():
        body = per_scenario["crosses_midnight"]
        date_field = next(
            value for key, value in body.items() if key in {"VisitDate", "visitDate", "serviceDate"}
        )
        assert date_field == "2026-03-11", (
            f"{adapter_key} files an overnight visit against the wrong calendar day"
        )


def test_telephony_carries_a_documented_reason_rather_than_empty_coordinates() -> None:
    """A caregiver without a smartphone must still produce a compliant record.

    `06_Compliance_and_Regulatory_Requirements.md` Section 1 accepts telephony capture. What
    it does not accept is a location element that is simply blank, so the absence has to
    survive the field mapping with its reason attached.
    """
    for adapter_key, per_scenario in wire_bodies().items():
        body = per_scenario["telephony_no_coordinates"]
        location = next(
            value
            for key, value in body.items()
            if key in {"VisitLocation", "location", "serviceLocation"}
        )
        assert location.get("absence_reason") == "telephony_capture", (
            f"{adapter_key} drops the reason coordinates are missing"
        )
        assert "coordinates" not in location


def test_a_manual_entry_is_not_transmitted_as_a_gps_capture() -> None:
    """Transmitting a hand-entered visit as GPS-captured is a misrepresentation.

    Not a rounding error and not a display concern: it is a claim about how the visit was
    verified, made to a state, on a record an auditor will read.
    """
    for adapter_key, per_scenario in wire_bodies().items():
        body = per_scenario["manual_exception"]
        assert body["capture_method"] == "manual_exception", (
            f"{adapter_key} loses the capture method"
        )


def test_the_fixture_records_no_fabricated_aggregator_responses(recorded: dict) -> None:
    """Until a sandbox run, the response half is empty and must stay that way.

    A recorded acknowledgement nobody received would make this suite assert that our own
    guess is stable — which reads as coverage and proves less than nothing, because it would
    also survive the field map being wrong.
    """
    responses = recorded["responses"]
    assert set(responses) <= {"_comment"}, (
        "Aggregator responses appear in the fixture. Those may only be recorded from a real "
        "sandbox run."
    )


def test_the_recorder_is_deterministic() -> None:
    """Two runs produce identical output.

    A clock or a random UUID anywhere in the builders would make every regeneration a
    whole-file diff, and a whole-file diff is one nobody reads — which would quietly turn
    this from a control into a chore.
    """
    assert json.dumps(fixture_document(), sort_keys=True) == json.dumps(
        fixture_document(), sort_keys=True
    )
