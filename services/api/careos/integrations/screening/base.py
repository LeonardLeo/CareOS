"""The background-check and exclusion-screening contract every vendor adapter implements.

`07_Integration_Specifications.md` Section 1 requires every external dependency behind an
adapter so a vendor's shape never reaches domain logic. Screening gets the same treatment as
EVV and routing.

Two properties of this integration drive the design, and both differ from EVV:

**It is asynchronous over hours to days.** A criminal-history search touches county courts;
an exclusion-list check against OIG LEIE and GSA SAM is fast, but the bundle an agency
actually orders is not. So `order` returns an accepted request, not a verdict, and the
verdict arrives later through :meth:`fetch` or a vendor callback. `ScreeningRequest` already
models that; this is the interface that fills it.

**Its output is a gate, not a record.** `assert_assignable` refuses a caregiver for
publicly-funded work unless `exclusion_check_status` is `cleared`. A vendor response this
code cannot confidently read must therefore never resolve to `cleared` — :class:`ScreeningVerdict`
has no default and `from_vendor_status` raises on anything it does not recognise. An
unrecognised status leaving a caregiver blocked is a scheduling inconvenience. The same
status silently clearing them is a false-claims exposure.
"""

from __future__ import annotations

import abc
import enum
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class ScreeningError(RuntimeError):
    """The vendor could not be reached, or answered in a shape this adapter cannot read."""


class ScreeningCheck(enum.StrEnum):
    """The check types US-1.3.2 expects an onboarding bundle to cover.

    Ordered by what blocks scheduling. `exclusion_list` is the one `assert_assignable`
    consults; the others gate employment decisions the agency makes, not assignment.
    """

    exclusion_list = "exclusion_list"
    criminal_history = "criminal_history"
    sex_offender_registry = "sex_offender_registry"
    license_verification = "license_verification"


#: What an agency orders when it onboards someone. Exclusion screening is separated out
#: because it is the only one that recurs on a schedule — see `screening.rescreen`.
DEFAULT_ONBOARDING_CHECKS: tuple[ScreeningCheck, ...] = (
    ScreeningCheck.exclusion_list,
    ScreeningCheck.criminal_history,
    ScreeningCheck.sex_offender_registry,
)


class ScreeningVerdict(enum.StrEnum):
    """What the vendor concluded.

    Deliberately three-valued. `pending` is not an absence of an answer to be filled in with
    an optimistic default — it is the answer for most of the life of a request, and code that
    treats "not yet flagged" as "cleared" is the specific bug this enum exists to prevent.
    """

    pending = "pending"
    clear = "clear"
    flagged = "flagged"


@dataclass(frozen=True, slots=True)
class ScreeningSubject:
    """The identity a vendor needs to run a search.

    Carries the minimum a search requires and nothing more. Everything here is identity data
    under a BAA, so the narrowness is the point: an adapter cannot forward a field it was
    never handed.
    """

    caregiver_id: uuid.UUID
    legal_name: str
    date_of_birth: str | None = None
    #: Last four digits only unless a vendor demonstrably requires the full number. Most
    #: exclusion-list matching does not.
    ssn_last4: str | None = None
    state_code: str | None = None


@dataclass(frozen=True, slots=True)
class ScreeningOrder:
    """A vendor's acknowledgement that a search has been accepted.

    `vendor_request_id` is what later results are correlated on, so an adapter that cannot
    produce one has not successfully ordered anything and must raise instead.
    """

    vendor_request_id: str
    checks: tuple[ScreeningCheck, ...]
    submitted_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScreeningResult:
    """A verdict for one request, with the per-check detail behind it.

    `matches` holds whatever the vendor said about a hit. It is stored and shown to a human;
    nothing branches on its contents. Adjudicating a criminal-history match against
    fair-hiring law is a human decision under `06_Compliance_and_Regulatory_Requirements.md`
    Section 5, not a rule this system may encode.
    """

    vendor_request_id: str
    verdict: ScreeningVerdict
    completed_at: datetime | None = None
    per_check: dict[str, str] = field(default_factory=dict)
    matches: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_final(self) -> bool:
        return self.verdict is not ScreeningVerdict.pending

    def __post_init__(self) -> None:
        if self.is_final and self.completed_at is None:
            raise ValueError("A final screening result must carry a completion timestamp")


def verdict_from_vendor_status(
    status: str, *, mapping: dict[str, ScreeningVerdict]
) -> ScreeningVerdict:
    """Translate a vendor's status string using an adapter-supplied mapping.

    Raises on anything absent from the mapping rather than falling through to a default.
    Vendors add statuses; a new one arriving as an unhandled string must stop the pipeline
    and be seen, not be quietly bucketed. The failure is loud precisely because the
    optimistic version of this function would clear an excluded caregiver.
    """
    try:
        return mapping[status.strip().lower()]
    except KeyError as exc:
        raise ScreeningError(
            f"Unrecognised screening status {status!r}. Refusing to guess a verdict — "
            "add it to the adapter's status map."
        ) from exc


class ScreeningAdapter(abc.ABC):
    """Base class for a background-check vendor."""

    adapter_key: str

    def __init__(self, *, config: dict[str, Any] | None = None, sandbox: bool = True) -> None:
        self.config = config or {}
        self.sandbox = sandbox

    @abc.abstractmethod
    async def order(
        self, subject: ScreeningSubject, checks: tuple[ScreeningCheck, ...]
    ) -> ScreeningOrder:
        """Submit a search. Raises :class:`ScreeningError` if the vendor did not accept it."""

    @abc.abstractmethod
    async def fetch(self, vendor_request_id: str) -> ScreeningResult:
        """Poll for a verdict. Returns `pending` until the vendor has one."""

    def parse_callback(self, payload: dict[str, Any]) -> ScreeningResult:
        """Read a vendor-pushed result.

        Optional: a vendor with no callback support is polled instead. The default refuses
        rather than returning something empty, so a callback route wired to an adapter that
        cannot parse one fails at the first delivery instead of silently discarding results.
        """
        raise ScreeningError(f"{type(self).__name__} does not support vendor callbacks")

    def __repr__(self) -> str:
        mode = "sandbox" if self.sandbox else "production"
        return f"<{type(self).__name__} {self.adapter_key} ({mode})>"
