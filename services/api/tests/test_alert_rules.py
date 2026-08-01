"""The alerting rules refer to metrics this application actually exports.

`promtool test rules` cannot check this. Its unit tests run against `input_series` written by
hand in the same change as the rule, so a metric name misspelled in both — or a rule left
behind after a metric was renamed — passes every check and then sits silently in production
never firing. An alert that cannot fire is worse than no alert, because it is counted as
coverage.

This closes that loop from the other side: it reads the shipped rule file and asserts every
`careos_*` name in it exists in the registry the API serves. Renaming a metric now breaks the
build here instead of quietly disarming a page.

Deliberately reading `ops/prometheus/alerts.yml` rather than a copy. A test against a fixture
would verify the fixture.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from careos.core import metrics

RULES_FILE = Path(__file__).resolve().parents[3] / "ops" / "prometheus" / "alerts.yml"

#: Names appearing in an expression that are PromQL or Prometheus' own, not ours.
_NOT_OURS = {"up"}

#: A metric name in a PromQL expression: an identifier followed by a label matcher, a range
#: selector, a comparison, or the close of the function call it sits inside. Loose on purpose —
#: over-matching costs a name that is then found in the registry anyway, while under-matching
#: would silently skip the rule this file exists to check.
_SELECTOR = re.compile(r"\b([a-zA-Z_:][a-zA-Z0-9_:]*)\s*(?:\{|\[|\)|\s*[=<>!])")


def _exported_metric_names() -> set[str]:
    """Every series name the app can produce, including the suffixed histogram families."""
    names: set[str] = set()
    for metric in metrics.REGISTRY.collect():
        names.add(metric.name)
        for sample in metric.samples:
            names.add(sample.name)
        if metric.type == "histogram":
            names.update({f"{metric.name}_bucket", f"{metric.name}_count", f"{metric.name}_sum"})
        if metric.type == "counter":
            names.add(f"{metric.name}_total")
    return names


def _referenced_metric_names() -> dict[str, set[str]]:
    """Metric names each alert's expression selects, keyed by alert name."""
    rules = yaml.safe_load(RULES_FILE.read_text())
    referenced: dict[str, set[str]] = {}
    for group in rules["groups"]:
        for rule in group["rules"]:
            found = set(_SELECTOR.findall(rule["expr"]))
            referenced[rule["alert"]] = {
                name for name in found if name.startswith("careos_") or name in _NOT_OURS
            }
    return referenced


def test_the_rule_file_is_where_the_tests_think_it_is() -> None:
    """Without this, a moved file turns every assertion below into a vacuous pass."""
    assert RULES_FILE.is_file(), f"no alert rules at {RULES_FILE}"


def test_every_alert_refers_to_a_metric_we_actually_export() -> None:
    exported = _exported_metric_names()
    unknown: list[tuple[str, str]] = []
    for alert, names in _referenced_metric_names().items():
        for name in sorted(names):
            if name in _NOT_OURS:
                continue
            if name not in exported:
                unknown.append((alert, name))
    assert unknown == [], (
        f"alerts referring to metrics this API does not export — they can never fire: {unknown}"
    )


def test_every_alert_names_a_severity_that_alertmanager_routes() -> None:
    """A severity Alertmanager has no route for falls to the default receiver.

    Which is to say a page would arrive as a ticket, silently, and only during the incident
    that needed it.
    """
    routed = {"page", "ticket"}
    rules = yaml.safe_load(RULES_FILE.read_text())
    for group in rules["groups"]:
        for rule in group["rules"]:
            severity = rule.get("labels", {}).get("severity")
            assert severity in routed, (
                f"{rule['alert']} has severity {severity!r}, which Alertmanager does not route"
            )


def test_every_alert_says_what_to_do_about_it() -> None:
    """An alert without a description is a pager buzz with no next step.

    The length floor is crude but it is the difference between "EVV errors" and something a
    person woken at 3am can act on.
    """
    rules = yaml.safe_load(RULES_FILE.read_text())
    for group in rules["groups"]:
        for rule in group["rules"]:
            annotations = rule.get("annotations", {})
            assert annotations.get("summary"), f"{rule['alert']} has no summary"
            description = annotations.get("description", "")
            assert len(description) > 120, (
                f"{rule['alert']} has no useful description: {description!r}"
            )


@pytest.mark.parametrize(
    "metric_name",
    [
        "careos_rate_limit_degraded",
        "careos_evv_escalations_total",
        "careos_request_commit_failures_total",
        "careos_evv_anomalous_volume_total",
    ],
)
def test_the_signals_that_justified_this_work_are_alerted_on(metric_name: str) -> None:
    """Each of these exists because its failure mode is invisible without an alert.

    Exporting them and then never alerting is the halfway state this increment was meant to
    leave behind, so the link is asserted rather than assumed.
    """
    referenced = set().union(*_referenced_metric_names().values())
    assert metric_name in referenced, f"{metric_name} is exported but nothing alerts on it"
