"""Adverse-impact analysis for the hiring model.

`06_Compliance_and_Regulatory_Requirements.md` Section 5 requires a bias audit before Epic
1.2.2 ships and re-audits as the model or its inputs change; Section 9 puts that on an annual
cadence. `03_Technical_Architecture.md` Section 8 asks for it as a recurring compliance task,
not a one-time check. This module is the machinery for running it.

**Why this exists even though protected attributes cannot reach the scorer.** Excluding
protected attributes prevents *disparate treatment*. It does not prevent *disparate impact* —
a facially neutral feature can still produce a skewed outcome, which is the failure mode that
matters most here and the one an allowlist cannot detect. Only measuring outcomes finds it.

**Where the demographic data comes from.** Not from the applicant record. It is supplied to
this function by whoever runs the audit, from voluntary self-identification collected and
stored separately from the hiring pipeline — the standard arrangement, and the reason
`audit_ranking_outcomes` takes group labels as an argument rather than reading them from the
database. Nothing in CareOS's schema stores an applicant's race or sex, and nothing should.

The four-fifths rule (a selection-rate ratio below 0.8 relative to the most-selected group)
is the long-standing EEOC rule-of-thumb screen. It is a **screening heuristic, not a legal
verdict**: it is unreliable on small samples, and passing it is not a defence. Interpretation
belongs with employment counsel.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: EEOC four-fifths rule of thumb.
ADVERSE_IMPACT_THRESHOLD = 0.8

#: Below this many decisions in a group, the ratio is too noisy to act on. Reported as
#: `insufficient_data` rather than as a pass or a fail, because a spurious "pass" on four
#: applicants is worse than an honest "we cannot tell".
MIN_GROUP_SIZE = 30


@dataclass(frozen=True, slots=True)
class GroupOutcome:
    group: str
    total: int
    selected: int

    @property
    def selection_rate(self) -> float:
        return self.selected / self.total if self.total else 0.0


@dataclass(frozen=True, slots=True)
class AuditFinding:
    attribute: str
    group: str
    selection_rate: float
    reference_group: str
    reference_rate: float
    impact_ratio: float
    sufficient_data: bool

    @property
    def is_adverse(self) -> bool:
        """Adverse impact indicated — only meaningful where there is enough data."""
        return self.sufficient_data and self.impact_ratio < ADVERSE_IMPACT_THRESHOLD


@dataclass
class AuditReport:
    model_version: str
    run_at: datetime
    total_decisions: int
    findings: list[AuditFinding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def adverse_findings(self) -> list[AuditFinding]:
        return [f for f in self.findings if f.is_adverse]

    @property
    def passed(self) -> bool:
        """No adverse impact detected among groups with sufficient data.

        Deliberately not called `is_compliant`. This checks one screening heuristic; it is
        not a determination that the model is lawful.
        """
        return not self.adverse_findings

    def as_dict(self) -> dict[str, Any]:
        """Serializable form, for the durable compliance log Section 9 asks for."""
        return {
            "model_version": self.model_version,
            "run_at": self.run_at.isoformat(),
            "total_decisions": self.total_decisions,
            "passed": self.passed,
            "threshold": ADVERSE_IMPACT_THRESHOLD,
            "min_group_size": MIN_GROUP_SIZE,
            "findings": [
                {
                    "attribute": f.attribute,
                    "group": f.group,
                    "selection_rate": round(f.selection_rate, 4),
                    "reference_group": f.reference_group,
                    "reference_rate": round(f.reference_rate, 4),
                    "impact_ratio": round(f.impact_ratio, 4),
                    "sufficient_data": f.sufficient_data,
                    "adverse": f.is_adverse,
                }
                for f in self.findings
            ],
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class RankingDecision:
    """One scored applicant and what happened to them.

    `group_labels` maps an attribute name to this person's self-identified group, supplied
    by the audit caller from separately-held voluntary data — never from the hiring record.
    """

    applicant_id: str
    selected: bool
    group_labels: dict[str, str]


def audit_ranking_outcomes(decisions: list[RankingDecision], *, model_version: str) -> AuditReport:
    """Compute selection-rate ratios per group, per attribute.

    Each group is compared against the highest-selecting group for that attribute, which is
    how the four-fifths rule is conventionally applied.
    """
    report = AuditReport(
        model_version=model_version,
        run_at=datetime.now(UTC),
        total_decisions=len(decisions),
    )

    if not decisions:
        report.notes.append("No ranking decisions to audit.")
        return report

    by_attribute: dict[str, dict[str, list[RankingDecision]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for decision in decisions:
        for attribute, group in decision.group_labels.items():
            by_attribute[attribute][group].append(decision)

    if not by_attribute:
        report.notes.append(
            "No demographic labels supplied, so adverse impact cannot be assessed. "
            "Supply voluntary self-identification data held separately from the hiring "
            "pipeline (06_Compliance_and_Regulatory_Requirements.md Section 5)."
        )
        return report

    for attribute, groups in sorted(by_attribute.items()):
        outcomes = [
            GroupOutcome(
                group=group,
                total=len(members),
                selected=sum(1 for d in members if d.selected),
            )
            for group, members in sorted(groups.items())
        ]

        reference = max(outcomes, key=lambda o: o.selection_rate)
        if reference.selection_rate == 0.0:
            report.notes.append(
                f"No applicant in any {attribute} group was selected; impact ratios are undefined."
            )
            continue

        for outcome in outcomes:
            if outcome.group == reference.group:
                continue
            sufficient = outcome.total >= MIN_GROUP_SIZE and reference.total >= MIN_GROUP_SIZE
            report.findings.append(
                AuditFinding(
                    attribute=attribute,
                    group=outcome.group,
                    selection_rate=outcome.selection_rate,
                    reference_group=reference.group,
                    reference_rate=reference.selection_rate,
                    impact_ratio=outcome.selection_rate / reference.selection_rate,
                    sufficient_data=sufficient,
                )
            )
            if not sufficient:
                report.notes.append(
                    f"{attribute}={outcome.group}: {outcome.total} decisions is below the "
                    f"{MIN_GROUP_SIZE}-decision minimum; ratio reported but not actionable."
                )

    if report.adverse_findings:
        report.notes.append(
            "Adverse impact indicated. Do not ship or continue running this model version "
            "without employment-counsel review (06_Compliance_and_Regulatory_Requirements.md "
            "Section 5)."
        )
    return report


def required_sample_size(baseline_rate: float, minimum_detectable_ratio: float = 0.8) -> int:
    """Roughly how many decisions per group are needed to detect a given disparity.

    Useful before an audit: running one on a sample too small to detect anything produces a
    "pass" that means nothing. Two-proportion comparison at 80% power, alpha 0.05.
    """
    if not 0 < baseline_rate < 1:
        raise ValueError("baseline_rate must be strictly between 0 and 1")

    comparison_rate = baseline_rate * minimum_detectable_ratio
    pooled = (baseline_rate + comparison_rate) / 2
    effect = abs(baseline_rate - comparison_rate)
    if effect == 0:
        raise ValueError("minimum_detectable_ratio of 1.0 implies no detectable difference")

    z_alpha, z_beta = 1.96, 0.84
    numerator = (z_alpha * math.sqrt(2 * pooled * (1 - pooled))) + (
        z_beta
        * math.sqrt(baseline_rate * (1 - baseline_rate) + comparison_rate * (1 - comparison_rate))
    )
    return math.ceil((numerator / effect) ** 2)
