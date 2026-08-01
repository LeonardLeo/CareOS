"""Run the AI hiring bias audit and record the outcome.

`06_Compliance_and_Regulatory_Requirements.md` Section 5 requires a bias audit before Epic
1.2.2 ships and re-audits as the model or its inputs change; Section 9 puts it on an annual
cadence. This is the command that performs one, so the audit is an operation someone runs
rather than a library nobody calls.

**Demographic labels come from a file you supply, not from CareOS.** Nothing in the schema
stores an applicant's race or sex, deliberately — voluntary self-identification is collected
and held separately from the hiring pipeline. Point `--labels` at a JSON file mapping
applicant IDs to their self-identified groups:

    {"<applicant-uuid>": {"race": "group_a", "sex": "F"}, ...}

Usage:

    python -m careos.scripts.run_bias_audit --agency-id <uuid> --labels labels.json
    python -m careos.scripts.run_bias_audit --agency-id <uuid>   # sample-size check only

Exit codes: 0 clean, 1 adverse impact indicated, 2 could not run. Non-zero on adverse impact
so this can gate a release pipeline.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

from careos.db.session import tenant_session
from careos.modules.audit.compliance_log import record_review
from careos.modules.audit.compliance_log_models import ReviewOutcome, ReviewType
from careos.modules.recruiting.bias_audit import (
    MIN_GROUP_SIZE,
    RankingDecision,
    audit_ranking_outcomes,
    required_sample_size,
)
from careos.modules.recruiting.models import ApplicantProfile, PipelineStage
from careos.modules.recruiting.ranking import MODEL_VERSION

#: Reaching offer or hire counts as selection. Screening is too early to be the outcome of
#: interest — the ranking's influence shows up in who progresses past it.
SELECTED_STAGES = {PipelineStage.offer, PipelineStage.hired}


async def _load_decisions(
    agency_id: uuid.UUID, labels: dict[str, dict[str, str]]
) -> tuple[list[RankingDecision], int, str | None]:
    async with tenant_session(agency_id) as session:
        applicants = (
            (
                await session.execute(
                    select(ApplicantProfile).where(ApplicantProfile.ranking_score.is_not(None))
                )
            )
            .scalars()
            .all()
        )

    decisions = [
        RankingDecision(
            applicant_id=str(a.id),
            selected=a.pipeline_stage in SELECTED_STAGES,
            group_labels=labels.get(str(a.id), {}),
        )
        for a in applicants
    ]
    versions = {a.ranking_model_version for a in applicants if a.ranking_model_version}
    # More than one version in the sample means the audit spans a model change, which makes
    # the result hard to attribute. Reported rather than silently averaged.
    version = versions.pop() if len(versions) == 1 else None
    return decisions, len(applicants), version


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run the AI hiring bias audit")
    parser.add_argument("--agency-id", required=True, type=uuid.UUID)
    parser.add_argument(
        "--labels",
        type=Path,
        help="JSON file mapping applicant ID to self-identified group labels, held "
        "separately from the hiring pipeline",
    )
    parser.add_argument(
        "--performed-by",
        default="automated:run_bias_audit",
        help="Who ran this audit, for the compliance log",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="Print the report without writing it to the compliance log",
    )
    args = parser.parse_args()

    labels: dict[str, dict[str, str]] = {}
    if args.labels:
        if not args.labels.exists():
            print(f"Labels file not found: {args.labels}", file=sys.stderr)
            return 2
        labels = json.loads(args.labels.read_text())

    decisions, total, version = await _load_decisions(args.agency_id, labels)
    if not decisions:
        print("No scored applicants found; nothing to audit.", file=sys.stderr)
        return 2

    report = audit_ranking_outcomes(decisions, model_version=version or MODEL_VERSION)
    payload = report.as_dict()
    print(json.dumps(payload, indent=2))

    selected = sum(1 for d in decisions if d.selected)
    if selected:
        needed = required_sample_size(selected / total)
        print(
            f"\nSample: {total} scored applicants, {selected} selected. "
            f"Detecting a four-fifths disparity at this selection rate needs roughly "
            f"{needed} decisions per group (minimum {MIN_GROUP_SIZE}).",
            file=sys.stderr,
        )

    if version is None:
        report.notes.append(
            "Sample spans more than one model version, or none was recorded; attribute "
            "results with care."
        )

    if report.adverse_findings:
        outcome = ReviewOutcome.failed
    elif not report.findings:
        # No findings means the audit could not assess anything — usually missing labels.
        # That is not a pass.
        outcome = ReviewOutcome.inconclusive
    elif any(not f.sufficient_data for f in report.findings):
        outcome = ReviewOutcome.passed_with_findings
    else:
        outcome = ReviewOutcome.passed

    if not args.no_record:
        async with tenant_session(args.agency_id) as session:
            await record_review(
                session,
                principal=None,
                agency_id=args.agency_id,
                review_type=ReviewType.ai_hiring_bias_audit,
                outcome=outcome,
                performed_by=args.performed_by,
                model_version=version or MODEL_VERSION,
                summary=(
                    f"{outcome.value}: {len(report.adverse_findings)} adverse finding(s) "
                    f"across {total} scored applicants"
                ),
                details=payload,
            )
        print(f"\nRecorded in the compliance log as: {outcome.value}", file=sys.stderr)

    if outcome is ReviewOutcome.failed:
        print(
            "\nADVERSE IMPACT INDICATED. Do not continue using this model version for "
            "hiring decisions without employment-counsel review.",
            file=sys.stderr,
        )
        return 1
    if outcome is ReviewOutcome.inconclusive:
        print(
            "\nAudit was inconclusive — this is not a pass. Supply demographic labels via "
            "--labels to assess adverse impact.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
