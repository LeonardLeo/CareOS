"""In-process screening adapter for local development, tests, and CI.

Never registered for a real agency. Screening moves identity data — names, dates of birth,
partial SSNs — so `07_Integration_Specifications.md` Section 2's prohibition on testing
against production endpoints is sharper here than for EVV: a test run against a live vendor
would order real searches on real people and be billed for them.

**Stateless, and that is the whole design.** The first version of this adapter remembered its
orders in an instance attribute. Every test passed. Running the actual deployment topology —
the API orders a screening, the *worker process* polls for the verdict — produced
`No such loopback screening request` on the first tick and could never have resolved
anything, because the worker's adapter instance had never seen the order. A real vendor
adapter holds no such state: it asks the vendor about a request id. This one now does the
same thing, with the id itself standing in for the vendor.

So the verdict and the readiness time are encoded into `vendor_request_id` at order time and
read back out of it at fetch time. Any process holding the id gets the same answer, which is
the property the real integration has and the property the deployment needs.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from careos.integrations.screening.base import (
    ScreeningAdapter,
    ScreeningCheck,
    ScreeningError,
    ScreeningOrder,
    ScreeningResult,
    ScreeningSubject,
    ScreeningVerdict,
    verdict_from_vendor_status,
)

#: A subject whose legal name contains this (case-insensitively) comes back flagged. Names are
#: the lever because a test fixture already controls them, so arranging a flagged caregiver
#: needs no reaching into the adapter.
FLAGGED_NAME_MARKER = "excluded"

#: How long a deferred order stays pending. Long enough that a test which does not advance
#: the clock sees a genuine pending state, short enough to be waited out deliberately.
DEFAULT_PENDING_SECONDS = 3600.0

#: The status vocabulary this fake vendor speaks, mapped the way a real adapter maps one.
#: Written out rather than reusing the enum so the translation step is exercised in tests
#: instead of being an identity function nobody notices is missing.
VENDOR_STATUS_MAP = {
    "in_progress": ScreeningVerdict.pending,
    "no_records_found": ScreeningVerdict.clear,
    "records_found": ScreeningVerdict.flagged,
}

_PREFIX = "loopback"


def _encode(*, flagged: bool, ready_at: float) -> str:
    """Build a request id that carries its own answer.

    `loopback-<records_found|no_records_found>-<unix ready time>-<uuid>`. Ugly on purpose:
    anyone reading it in a log should see immediately that this is a fixture and not a real
    vendor reference.
    """
    outcome = "records_found" if flagged else "no_records_found"
    # Floored, not rounded. `{:.0f}` rounds to nearest, so an order placed at x.6 seconds
    # became ready at x+1 and read as pending for the next four hundred milliseconds — which
    # is exactly long enough for a test that orders and immediately fetches to fail.
    return f"{_PREFIX}-{outcome}-{int(ready_at)}-{uuid.uuid4()}"


def _decode(vendor_request_id: str) -> tuple[str, float]:
    """Read the final status and readiness time back out. Raises on anything else.

    Refusing an id this adapter did not mint matters: a malformed or foreign reference must
    not resolve to a verdict, for the same reason `verdict_from_vendor_status` refuses an
    unmapped status.
    """
    parts = vendor_request_id.split("-", 3)
    if len(parts) != 4 or parts[0] != _PREFIX:
        raise ScreeningError(f"Not a loopback screening request: {vendor_request_id!r}")
    _, outcome, ready_text, _rest = parts
    if outcome not in {"records_found", "no_records_found"}:
        raise ScreeningError(f"Unreadable loopback screening request: {vendor_request_id!r}")
    try:
        ready_at = float(ready_text)
    except ValueError as exc:
        raise ScreeningError(
            f"Unreadable loopback screening request: {vendor_request_id!r}"
        ) from exc
    return outcome, ready_at


class LoopbackScreeningAdapter(ScreeningAdapter):
    adapter_key = "loopback"
    vendor_name = "Loopback screening (development only)"

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        sandbox: bool = True,
        complete_immediately: bool = True,
        pending_seconds: float = DEFAULT_PENDING_SECONDS,
    ) -> None:
        super().__init__(config=config, sandbox=sandbox)
        self.complete_immediately = complete_immediately
        self.pending_seconds = pending_seconds
        #: Everything ordered *by this instance*, so a test can assert on what was actually
        #: sent to the vendor — including that it was not sent more identity data than the
        #: search needed. Never consulted when answering a fetch; that is the point.
        self.orders: list[dict[str, Any]] = []
        #: Check types by request id, same-process only. Enriches `per_check` when this
        #: instance happens to have placed the order, and its absence changes no verdict.
        self._checks: dict[str, tuple[ScreeningCheck, ...]] = {}

    # -- ordering ------------------------------------------------------------------------

    async def order(
        self, subject: ScreeningSubject, checks: tuple[ScreeningCheck, ...]
    ) -> ScreeningOrder:
        if not checks:
            raise ScreeningError("A screening order must name at least one check")

        flagged = FLAGGED_NAME_MARKER in subject.legal_name.lower()
        ready_at = time.time() + (0.0 if self.complete_immediately else self.pending_seconds)
        vendor_request_id = _encode(flagged=flagged, ready_at=ready_at)

        self._checks[vendor_request_id] = checks
        self.orders.append(
            {
                "vendor_request_id": vendor_request_id,
                "caregiver_id": str(subject.caregiver_id),
                "legal_name": subject.legal_name,
                "date_of_birth": subject.date_of_birth,
                "ssn_last4": subject.ssn_last4,
                "checks": [c.value for c in checks],
            }
        )
        return ScreeningOrder(
            vendor_request_id=vendor_request_id,
            checks=checks,
            raw={"accepted": True},
        )

    # -- results -------------------------------------------------------------------------

    async def fetch(self, vendor_request_id: str) -> ScreeningResult:
        outcome, ready_at = _decode(vendor_request_id)
        status = outcome if time.time() >= ready_at else "in_progress"
        return self._result(vendor_request_id, status)

    def _result(self, vendor_request_id: str, vendor_status: str) -> ScreeningResult:
        verdict = verdict_from_vendor_status(vendor_status, mapping=VENDOR_STATUS_MAP)
        checks = self._checks.get(vendor_request_id, ())
        return ScreeningResult(
            vendor_request_id=vendor_request_id,
            verdict=verdict,
            completed_at=None if verdict is ScreeningVerdict.pending else datetime.now(UTC),
            per_check={c.value: vendor_status for c in checks},
            matches=(
                [
                    {
                        "source": "OIG LEIE",
                        "note": "Loopback fixture match — not a real exclusion",
                    }
                ]
                if verdict is ScreeningVerdict.flagged
                else []
            ),
            raw={"status": vendor_status},
        )

    def parse_callback(self, payload: dict[str, Any]) -> ScreeningResult:
        vendor_request_id = payload.get("vendor_request_id")
        status = payload.get("status")
        if not isinstance(vendor_request_id, str) or not isinstance(status, str):
            raise ScreeningError(
                "Screening callback must carry a string vendor_request_id and status"
            )
        # Validates the id before trusting the status. A callback naming a request this
        # adapter could not have minted is either misrouted or forged, and both need to
        # surface rather than write a verdict.
        _decode(vendor_request_id)
        return self._result(vendor_request_id, status)
