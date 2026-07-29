"""Generic compliance rules engine.

`02_Product_Requirements_Document.md` Section 6 is explicit that this must be built
generically in Phase 1 rather than as a one-off for EVV exception alerting, because Phase 2's
compliance copilot and Phase 3's claim scrubber are the same machinery pointed at different
subjects. So nothing here knows what an EVV record is — rules are registered against a
subject name and evaluated over a context dict.

Two properties the later phases depend on:

* **Rules are data-driven where they can be.** Thresholds come from `RuleConfig`, which an
  agency can override without a deploy (PRD US-2.2.3 wants a rules-configuration UI, not
  hardcoded logic). Rule *logic* is still code; only its parameters are configurable.
* **Deterministic rules are authoritative.** `03_Technical_Architecture.md` Section 5:
  an LLM layer may advise or flag, but anything that blocks a claim or a schedule is a
  deterministic rule evaluated here. Findings carry `blocking` for exactly that reason.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


class Severity(enum.StrEnum):
    info = "info"
    warning = "warning"
    #: Requires agency action before the underlying record is billable or auditable.
    critical = "critical"


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule violation against one entity."""

    rule_key: str
    severity: Severity
    message: str
    entity_type: str
    entity_id: Any
    details: dict[str, Any] = field(default_factory=dict)
    #: True when the finding must prevent the operation rather than merely annotate it.
    blocking: bool = False


@dataclass(frozen=True, slots=True)
class RuleConfig:
    """Per-agency parameters for a rule.

    `enabled` and `severity` are overridable so an agency with a stricter payer contract can
    escalate a warning to critical without new code.
    """

    enabled: bool = True
    severity: Severity | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Rule:
    """A registered rule.

    `evaluate` receives the context and the resolved config, and returns zero or more
    findings. Returning a list rather than a bool lets one rule report several distinct
    problems — a visit can be both outside its geofence and missing a service code.
    """

    key: str
    subject: str
    default_severity: Severity
    description: str
    evaluate: Callable[[dict[str, Any], RuleConfig], Iterable[Finding]]
    blocking: bool = False


class RuleEngine:
    """Registry and evaluator.

    Rules are registered per subject (``"visit"``, ``"visit_note"``, ``"claim_line"``).
    Phase 2 and 3 register their own subjects against this same instance.
    """

    def __init__(self) -> None:
        self._rules: dict[str, list[Rule]] = {}

    def register(self, rule: Rule) -> Rule:
        existing = {r.key for r in self._rules.get(rule.subject, [])}
        if rule.key in existing:
            raise ValueError(f"Rule {rule.key!r} is already registered for {rule.subject!r}")
        self._rules.setdefault(rule.subject, []).append(rule)
        return rule

    def rules_for(self, subject: str) -> tuple[Rule, ...]:
        return tuple(self._rules.get(subject, ()))

    def all_rules(self) -> tuple[Rule, ...]:
        return tuple(rule for rules in self._rules.values() for rule in rules)

    def evaluate(
        self,
        subject: str,
        context: dict[str, Any],
        *,
        config: dict[str, RuleConfig] | None = None,
    ) -> list[Finding]:
        """Run every enabled rule for `subject` and collect the findings.

        One rule raising does not suppress the others: a bug in a single rule must not
        blind the agency to every other compliance problem on the same record. The failure
        surfaces as its own critical finding instead.
        """
        config = config or {}
        findings: list[Finding] = []

        for rule in self.rules_for(subject):
            rule_config = config.get(rule.key, RuleConfig())
            if not rule_config.enabled:
                continue
            effective_severity = rule_config.severity or rule.default_severity
            try:
                produced = list(rule.evaluate(context, rule_config))
            except Exception as exc:  # noqa: BLE001 - deliberate: see docstring
                findings.append(
                    Finding(
                        rule_key=f"{rule.key}.evaluation_error",
                        severity=Severity.critical,
                        message=f"Compliance rule {rule.key!r} failed to evaluate: {exc}",
                        entity_type=subject,
                        entity_id=context.get("entity_id"),
                        details={"rule_key": rule.key, "error": str(exc)},
                    )
                )
                continue

            for finding in produced:
                # The rule states the problem; the engine applies the agency's configured
                # severity, so rules never have to consult configuration themselves.
                findings.append(
                    Finding(
                        rule_key=finding.rule_key,
                        severity=effective_severity,
                        message=finding.message,
                        entity_type=finding.entity_type,
                        entity_id=finding.entity_id,
                        details=finding.details,
                        blocking=rule.blocking or finding.blocking,
                    )
                )
        return findings

    @staticmethod
    def blocking_findings(findings: Iterable[Finding]) -> list[Finding]:
        return [f for f in findings if f.blocking]


#: Process-wide engine. Phase 1 rules register on import of
#: `careos.modules.compliance_rules.evv_rules`; later phases add their own modules.
engine = RuleEngine()
