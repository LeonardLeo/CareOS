"""Explainable scoring for applicants and for shift matching.

`03_Technical_Architecture.md` Section 5 says candidate/shift ranking starts as a
hosted-LLM-prompted scoring function and that a lightweight in-house model is warranted only
if latency or cost demands it — explicitly warning against over-building before then.

This is the deterministic scorer that sits behind that decision. Choosing it first is not
avoidance of the AI/ML work; it is a consequence of the constraints:

* It is **auditable**. `06_Compliance...` Section 5 requires a bias audit, and re-audit as
  the model or its inputs change. Auditing a weighted-sum over a fixed feature allowlist is
  tractable; auditing a prompt over free-text résumés is a research project.
* It is **fast**. The PRD's performance NFR gives AI ranking under 5 seconds, and shift
  ranking runs inside the scheduler's live gap-fill loop.
* It is **explainable by construction**. US-1.2.2 requires the top three factors behind
  every score. Here they fall out of the arithmetic rather than being a second LLM call
  asking the model to justify itself — which produces plausible narration, not necessarily
  the actual reason.

`Scorer` is the seam for the LLM version. When one arrives it implements the same protocol,
consumes the same allowlisted features, and must still return per-factor contributions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from careos.modules.recruiting.features import (
    FeatureWeight,
    assert_features_permitted,
)

#: Bump when weights or logic change. Recorded on every scored row so a later bias audit can
#: attribute decisions to a specific revision (`applicant_profile.ranking_model_version`).
MODEL_VERSION = "deterministic-v1"

#: Number of explanatory factors surfaced, per US-1.2.2.
TOP_FACTORS = 3


@dataclass(frozen=True, slots=True)
class Score:
    """A score plus the reasoning behind it.

    `factors` is never empty when `value` is set — the database enforces this too, via
    `ck_applicant_ranking_score_requires_factors`. An unexplained score is not a valid
    output of this system.
    """

    value: float
    factors: list[FeatureWeight]
    model_version: str = MODEL_VERSION

    def top_factors(self, limit: int = TOP_FACTORS) -> list[FeatureWeight]:
        """The strongest contributors, largest absolute contribution first.

        Sorted by magnitude rather than by value so that a strongly *negative* factor — the
        reason a candidate ranked low — is surfaced rather than buried. "Why is this person
        at the bottom?" is as important a question as "why the top?".
        """
        return sorted(self.factors, key=lambda f: abs(f.weight), reverse=True)[:limit]

    def as_payload(self) -> list[dict[str, Any]]:
        """Shape stored in `ranking_factors` and returned by the API."""
        return [
            {"factor": f.feature, "weight": round(f.weight, 4), "rationale": f.rationale}
            for f in self.top_factors()
        ]


class Scorer(Protocol):
    """Anything that turns allowlisted features into an explained score."""

    model_version: str

    def score(self, features: dict[str, Any]) -> Score: ...


@dataclass(frozen=True, slots=True)
class WeightedFeature:
    """How one feature converts into a contribution."""

    #: Relative importance. Weights across a profile are normalized, so these are ratios,
    #: not percentages, and adding a feature does not require rebalancing every other one.
    weight: float
    #: Human-readable explanation template; receives the normalized value.
    describe: Any
    #: True when a low value should count against the candidate rather than merely not
    #: count for them.
    penalizing: bool = False


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _proximity_value(miles: float) -> float:
    """Convert distance to a 0–1 desirability.

    Linear decay to zero at 60 miles. Home care is local work: an hour of unpaid driving
    between visits is a real cause of the turnover this product exists to reduce, so
    distance is weighted meaningfully rather than as a tiebreak.
    """
    return _clamp(1.0 - (miles / 60.0))


#: Applicant ranking profile (Epic 1.2).
APPLICANT_WEIGHTS: dict[str, WeightedFeature] = {
    "certification_match": WeightedFeature(
        weight=0.40,
        describe=lambda v: (
            "Holds the certifications this role requires"
            if v >= 0.99
            else f"Holds {v:.0%} of the certifications this role requires"
        ),
    ),
    "geo_proximity_miles": WeightedFeature(
        weight=0.35,
        describe=lambda v: f"Proximity to this role's open shifts scores {v:.0%}",
    ),
    "availability_overlap": WeightedFeature(
        weight=0.25,
        describe=lambda v: f"Available for {v:.0%} of the currently unfilled shifts",
    ),
}

#: Shift matching profile (Epic 1.4). Same machinery, different weighting: continuity of care
#: matters to clients and to outcomes, and overtime exposure is a real cost the scheduler is
#: trying to manage.
SHIFT_WEIGHTS: dict[str, WeightedFeature] = {
    "certification_match": WeightedFeature(
        weight=0.30,
        describe=lambda v: (
            "Holds every certification this visit requires"
            if v >= 0.99
            else f"Holds {v:.0%} of the certifications this visit requires"
        ),
    ),
    "geo_proximity_miles": WeightedFeature(
        weight=0.25,
        describe=lambda v: f"Drive-time proximity to this client scores {v:.0%}",
    ),
    "availability_overlap": WeightedFeature(
        weight=0.20,
        describe=lambda v: (
            "Free at this visit's time" if v >= 0.99 else "Has a scheduling conflict"
        ),
    ),
    "continuity_of_care": WeightedFeature(
        weight=0.15,
        describe=lambda v: "Has cared for this client before" if v > 0 else "New to this client",
    ),
    "overtime_headroom": WeightedFeature(
        weight=0.10,
        describe=lambda v: (
            "Assigning this visit stays within standard hours"
            if v >= 0.99
            else "Assigning this visit risks overtime"
        ),
        penalizing=True,
    ),
}


@dataclass
class WeightedSumScorer:
    """Normalized weighted sum over allowlisted features.

    Features absent from the input are skipped and their weight is removed from the
    denominator, rather than treated as zero. Missing data is not evidence of a bad
    candidate — an applicant who has not listed availability yet should not be ranked below
    one who listed poor availability.
    """

    weights: dict[str, WeightedFeature]
    model_version: str = MODEL_VERSION
    _: dict[str, Any] = field(default_factory=dict, repr=False)

    def score(self, features: dict[str, Any]) -> Score:
        # Validation happens here, inside the scorer, so no caller can bypass it.
        assert_features_permitted(features)

        contributions: list[FeatureWeight] = []
        total_weight = 0.0
        weighted_sum = 0.0

        for name, spec in self.weights.items():
            if name not in features or features[name] is None:
                continue
            raw = features[name]
            value = (
                _proximity_value(float(raw))
                if name == "geo_proximity_miles"
                else _clamp(float(raw))
            )

            total_weight += spec.weight
            weighted_sum += spec.weight * value
            contributions.append(
                FeatureWeight(
                    feature=name,
                    # Contribution toward the final score, so the numbers a scheduler sees
                    # actually add up to the score shown next to them.
                    weight=spec.weight * value,
                    rationale=spec.describe(value),
                )
            )

        if total_weight == 0.0:
            # No usable signal. Returning 0.0 would rank this candidate as actively bad;
            # 0.0 with an explicit explanation says "we don't know", which is the truth.
            return Score(
                value=0.0,
                factors=[
                    FeatureWeight(
                        feature="insufficient_data",
                        weight=0.0,
                        rationale="Not enough information to rank this candidate yet",
                    )
                ],
                model_version=self.model_version,
            )

        normalized = [
            FeatureWeight(f.feature, f.weight / total_weight, f.rationale) for f in contributions
        ]
        return Score(
            value=round(weighted_sum / total_weight, 4),
            factors=normalized,
            model_version=self.model_version,
        )


applicant_scorer = WeightedSumScorer(weights=APPLICANT_WEIGHTS)
shift_scorer = WeightedSumScorer(weights=SHIFT_WEIGHTS)


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line distance in miles, for applicant-level proximity.

    Applicant ranking compares one candidate against every currently-open shift, so this
    stays a cheap local calculation rather than going through the routing adapter — that
    would be one provider call per candidate per open shift. Shift *matching*, which scores a
    roster against a single visit, does use the adapter and reports real travel time
    (`careos.integrations.routing`).

    Delegates to the routing module so there is one implementation of the formula.
    """
    from careos.integrations.routing.base import GeoPoint
    from careos.integrations.routing.base import haversine_miles as _haversine

    return _haversine(GeoPoint(lat1, lng1), GeoPoint(lat2, lng2))
