"""The feature contract for scoring people.

`06_Compliance_and_Regulatory_Requirements.md` Section 5 forbids the applicant-ranking model
from using — **or proxying for** — protected-class attributes. That is easy to state, easy to
agree with, and easy to violate by accident three refactors later when someone adds a field
to the feature dict because it was conveniently in scope.

So this module makes it structural rather than advisory:

* :data:`ALLOWED_FEATURES` is a closed allowlist. Scoring rejects any feature outside it —
  an allowlist, not a denylist, because a denylist only catches attributes someone thought
  to forbid.
* :data:`PROHIBITED_FEATURES` names protected attributes and their common proxies
  explicitly, so a violation produces an error that says *why* rather than just "unknown
  feature".
* Proxies are the subtle part and are treated as seriously as the attributes themselves.
  A ZIP code correlates with race; a graduation year reveals age; a name suggests national
  origin and sex. None of these are "protected attributes" literally, and all of them are
  prohibited here.

Geographic proximity is deliberately permitted but expressed only as **distance in miles to
a specific open shift** (`geo_proximity_miles`), never as a location identifier. Distance to a
job is a genuine operational requirement — a caregiver two hours away cannot staff the visit —
whereas ZIP code or neighbourhood is a race proxy with no additional operational value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Features the scorer may use. Each maps to a real operational requirement of the job.
ALLOWED_FEATURES: frozenset[str] = frozenset(
    {
        # Can they legally and competently do this work?
        "certification_match",
        "credentials_valid",
        "exclusion_cleared",
        # Can they physically be there?
        "geo_proximity_miles",
        "availability_overlap",
        "continuity_of_care",
        # Employment/scheduling constraints
        "overtime_headroom",
        "years_experience",
        # Performance signals from work actually done for this agency
        "reliability_score",
        "prior_visits_with_client",
    }
)

#: Protected attributes and known proxies. Named so violations fail loudly and legibly.
#: The value explains why, and that text reaches the exception message.
PROHIBITED_FEATURES: dict[str, str] = {
    "race": "protected class",
    "ethnicity": "protected class",
    "color": "protected class",
    "national_origin": "protected class",
    "sex": "protected class",
    "gender": "protected class",
    "age": "protected class",
    "date_of_birth": "reveals age",
    "dob": "reveals age",
    "graduation_year": "proxy for age",
    "disability": "protected class",
    "religion": "protected class",
    "familial_status": "protected class",
    "marital_status": "protected class",
    "pregnancy": "protected class",
    "veteran_status": "protected class",
    "citizenship": "protected class (work authorization is a separate eligibility gate)",
    "zip_code": "proxy for race and national origin",
    "postal_code": "proxy for race and national origin",
    "neighborhood": "proxy for race and national origin",
    "address": "proxy for race and national origin",
    "name": "proxy for national origin and sex",
    "legal_name": "proxy for national origin and sex",
    "photo": "reveals multiple protected attributes",
    "school_name": "proxy for race and national origin",
    "language_spoken_at_home": "proxy for national origin",
    "salary_history": "perpetuates protected-class pay disparities and is banned in "
    "several jurisdictions",
    "credit_score": "proxy for race and disparate-impact risk",
    "arrest_record": "proxy for race; only adjudicated convictions relevant to the role "
    "may be considered, and that is the screening gate's job, not the ranking model's",
}


class ProhibitedFeatureError(ValueError):
    """A protected attribute, or a known proxy for one, reached the scorer.

    Raised rather than dropped silently. A silently-ignored protected attribute is
    indistinguishable from one being used, and the whole point is to be able to demonstrate
    to a regulator that it could not have been used.
    """


class UnknownFeatureError(ValueError):
    """A feature outside the allowlist reached the scorer."""


def assert_features_permitted(features: dict[str, Any]) -> None:
    """Validate a feature dict before it reaches any scoring function.

    Called by the scorer itself, not by its callers, so there is no path to a score that
    skipped the check.
    """
    prohibited = sorted(set(features) & set(PROHIBITED_FEATURES))
    if prohibited:
        raise ProhibitedFeatureError(
            "Refusing to score: these inputs are protected-class attributes or known "
            "proxies for them — "
            + "; ".join(f"{name} ({PROHIBITED_FEATURES[name]})" for name in prohibited)
            + ". See 06_Compliance_and_Regulatory_Requirements.md Section 5."
        )

    unknown = sorted(set(features) - ALLOWED_FEATURES)
    if unknown:
        raise UnknownFeatureError(
            f"Refusing to score: {unknown} are not in the scoring allowlist. Add a feature "
            "to ALLOWED_FEATURES only after confirming it reflects a genuine requirement of "
            "the job and does not proxy for a protected class."
        )


@dataclass(frozen=True, slots=True)
class FeatureWeight:
    """One feature's contribution to a score.

    `rationale` is written for a human reading an explanation in the UI, not for a
    developer reading logs — schedulers and, eventually, auditors are the audience.
    """

    feature: str
    weight: float
    rationale: str
