"""Fair-hiring guarantees for the ranking model.

`06_Compliance_and_Regulatory_Requirements.md` Section 5 forbids the ranking model from using
or proxying for protected-class attributes, and requires a bias audit before Epic 1.2.2 ships.
These tests are the evidence that the first constraint holds structurally, and that the audit
tooling for the second actually detects disparity.

They are not a substitute for the counsel review that document requires.
"""

from __future__ import annotations

import pytest

from careos.modules.recruiting.bias_audit import (
    ADVERSE_IMPACT_THRESHOLD,
    MIN_GROUP_SIZE,
    RankingDecision,
    audit_ranking_outcomes,
    required_sample_size,
)
from careos.modules.recruiting.features import (
    ALLOWED_FEATURES,
    PROHIBITED_FEATURES,
    ProhibitedFeatureError,
    UnknownFeatureError,
    assert_features_permitted,
)
from careos.modules.recruiting.ranking import (
    APPLICANT_WEIGHTS,
    SHIFT_WEIGHTS,
    applicant_scorer,
    shift_scorer,
)

# --- The allowlist ------------------------------------------------------------------------


def test_allowed_and_prohibited_never_overlap() -> None:
    """A feature cannot be both permitted and forbidden."""
    assert not (ALLOWED_FEATURES & set(PROHIBITED_FEATURES))


def test_every_weighted_feature_is_allowlisted() -> None:
    """A scoring profile cannot reference a feature the allowlist does not permit."""
    for profile in (APPLICANT_WEIGHTS, SHIFT_WEIGHTS):
        assert set(profile) <= ALLOWED_FEATURES


@pytest.mark.parametrize(
    "attribute",
    ["race", "sex", "age", "religion", "disability", "national_origin", "familial_status"],
)
def test_protected_attributes_are_refused(attribute: str) -> None:
    with pytest.raises(ProhibitedFeatureError, match="protected"):
        assert_features_permitted({attribute: 1.0})


@pytest.mark.parametrize(
    "proxy",
    [
        "zip_code",
        "date_of_birth",
        "graduation_year",
        "name",
        "school_name",
        "salary_history",
        "credit_score",
        "arrest_record",
        "language_spoken_at_home",
    ],
)
def test_known_proxies_are_refused(proxy: str) -> None:
    """Proxies matter as much as the attributes themselves — this is the subtle failure."""
    with pytest.raises(ProhibitedFeatureError):
        assert_features_permitted({proxy: 1.0})


def test_unknown_features_are_refused() -> None:
    """An allowlist, not a denylist: anything unrecognised is rejected by default.

    A denylist would only ever catch attributes someone thought to forbid.
    """
    with pytest.raises(UnknownFeatureError, match="allowlist"):
        assert_features_permitted({"favourite_colour": 1.0})


def test_the_scorer_itself_enforces_the_allowlist() -> None:
    """Validation lives inside the scorer, so no caller can route around it."""
    with pytest.raises(ProhibitedFeatureError):
        applicant_scorer.score({"certification_match": 1.0, "zip_code": 90210})


def test_error_message_explains_why() -> None:
    """A violation should teach, not just fail."""
    with pytest.raises(ProhibitedFeatureError) as exc:
        assert_features_permitted({"zip_code": 1})
    message = str(exc.value)
    assert "proxy for race" in message
    assert "Section 5" in message


# --- Explainability -----------------------------------------------------------------------


def test_every_score_carries_factors() -> None:
    """US-1.2.2: no bare, unexplained numbers."""
    score = applicant_scorer.score(
        {"certification_match": 1.0, "geo_proximity_miles": 5.0, "availability_overlap": 0.8}
    )
    assert score.value > 0
    assert score.factors
    assert all(f.rationale for f in score.factors)


def test_factors_are_capped_at_three() -> None:
    score = shift_scorer.score(
        {
            "certification_match": 1.0,
            "geo_proximity_miles": 2.0,
            "availability_overlap": 1.0,
            "continuity_of_care": 1.0,
            "overtime_headroom": 1.0,
        }
    )
    assert len(score.as_payload()) == 3


def test_factors_are_ordered_by_influence() -> None:
    score = applicant_scorer.score(
        {"certification_match": 1.0, "geo_proximity_miles": 55.0, "availability_overlap": 0.2}
    )
    weights = [f["weight"] for f in score.as_payload()]
    assert weights == sorted(weights, key=abs, reverse=True)


def test_score_records_its_model_version() -> None:
    """A later bias audit must be able to attribute a decision to a model revision."""
    assert applicant_scorer.score({"certification_match": 1.0}).model_version


def test_missing_features_do_not_penalize() -> None:
    """Absent data is not evidence of a bad candidate.

    An applicant who has not filled in availability should not rank below one who supplied
    poor availability.
    """
    partial = applicant_scorer.score({"certification_match": 1.0})
    explicit_zero = applicant_scorer.score(
        {"certification_match": 1.0, "availability_overlap": 0.0}
    )
    assert partial.value > explicit_zero.value


def test_no_usable_signal_says_so_rather_than_scoring_zero() -> None:
    score = applicant_scorer.score({})
    assert score.value == 0.0
    assert score.factors[0].feature == "insufficient_data"
    assert "not enough information" in score.factors[0].rationale.lower()


def test_better_candidate_scores_higher() -> None:
    strong = applicant_scorer.score(
        {"certification_match": 1.0, "geo_proximity_miles": 3.0, "availability_overlap": 1.0}
    )
    weak = applicant_scorer.score(
        {"certification_match": 0.2, "geo_proximity_miles": 50.0, "availability_overlap": 0.2}
    )
    assert strong.value > weak.value
    assert 0.0 <= weak.value <= strong.value <= 1.0


def test_distance_decays_score() -> None:
    near = applicant_scorer.score({"geo_proximity_miles": 2.0})
    far = applicant_scorer.score({"geo_proximity_miles": 50.0})
    assert near.value > far.value


def test_distance_beyond_the_horizon_floors_at_zero() -> None:
    assert applicant_scorer.score({"geo_proximity_miles": 500.0}).value == 0.0


# --- Bias audit ---------------------------------------------------------------------------


def _decisions(group: str, total: int, selected: int, attribute: str = "race") -> list:
    return [
        RankingDecision(
            applicant_id=f"{group}-{i}",
            selected=i < selected,
            group_labels={attribute: group},
        )
        for i in range(total)
    ]


def test_balanced_outcomes_pass() -> None:
    decisions = _decisions("A", 100, 50) + _decisions("B", 100, 48)
    report = audit_ranking_outcomes(decisions, model_version="test-v1")
    assert report.passed
    assert not report.adverse_findings


def test_adverse_impact_is_detected() -> None:
    """Group B selected at half the rate of group A — well under four-fifths."""
    decisions = _decisions("A", 100, 60) + _decisions("B", 100, 25)
    report = audit_ranking_outcomes(decisions, model_version="test-v1")

    assert not report.passed
    finding = report.adverse_findings[0]
    assert finding.group == "B"
    assert finding.reference_group == "A"
    assert finding.impact_ratio < ADVERSE_IMPACT_THRESHOLD
    assert any("counsel review" in note for note in report.notes)


def test_ratio_just_above_threshold_passes() -> None:
    decisions = _decisions("A", 100, 50) + _decisions("B", 100, 41)
    report = audit_ranking_outcomes(decisions, model_version="test-v1")
    assert report.passed


def test_small_groups_are_reported_but_not_actionable() -> None:
    """A spurious pass or fail on a handful of applicants is worse than admitting ignorance."""
    decisions = _decisions("A", 10, 8) + _decisions("B", 10, 1)
    report = audit_ranking_outcomes(decisions, model_version="test-v1")

    assert report.findings, "the ratio should still be reported"
    assert not report.findings[0].sufficient_data
    assert report.passed, "an underpowered sample must not be treated as a failure"
    assert any(str(MIN_GROUP_SIZE) in note for note in report.notes)


def test_missing_demographic_labels_is_reported_not_silently_passed() -> None:
    """No labels means the audit could not run — that must not read as a clean bill."""
    decisions = [
        RankingDecision(applicant_id=str(i), selected=i % 2 == 0, group_labels={})
        for i in range(50)
    ]
    report = audit_ranking_outcomes(decisions, model_version="test-v1")
    assert not report.findings
    assert any("No demographic labels" in note for note in report.notes)


def test_empty_input_is_handled() -> None:
    report = audit_ranking_outcomes([], model_version="test-v1")
    assert report.total_decisions == 0
    assert any("No ranking decisions" in note for note in report.notes)


def test_multiple_attributes_are_audited_independently() -> None:
    decisions = []
    for i in range(100):
        decisions.append(
            RankingDecision(
                applicant_id=f"x{i}",
                selected=i < 60,
                group_labels={"race": "A", "sex": "F" if i % 2 else "M"},
            )
        )
    report = audit_ranking_outcomes(decisions, model_version="test-v1")
    assert {f.attribute for f in report.findings} <= {"race", "sex"}


def test_report_serializes_for_the_compliance_log() -> None:
    """Section 9 wants the outcome and date logged somewhere durable."""
    report = audit_ranking_outcomes(
        _decisions("A", 50, 30) + _decisions("B", 50, 10), model_version="test-v1"
    )
    payload = report.as_dict()
    assert payload["model_version"] == "test-v1"
    assert payload["passed"] is False
    assert payload["threshold"] == ADVERSE_IMPACT_THRESHOLD
    assert "run_at" in payload
    assert payload["findings"][0]["adverse"] is True


def test_required_sample_size_is_sane() -> None:
    """Guards against running an audit too small to detect anything."""
    needed = required_sample_size(0.5)
    assert 100 < needed < 2000
    # A rarer outcome needs a larger sample to detect the same relative disparity.
    assert required_sample_size(0.1) > needed


def test_required_sample_size_rejects_impossible_inputs() -> None:
    with pytest.raises(ValueError):
        required_sample_size(0.0)
    with pytest.raises(ValueError):
        required_sample_size(1.0)
