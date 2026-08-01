"""In-process adapter for local development, tests, and CI.

Never registered for a real state. It exists so the full clock-in → transmit →
acknowledge path can be exercised end to end without touching a vendor endpoint —
`07_Integration_Specifications.md` Section 2 forbids testing transmission logic against
production endpoints, and CI has no sandbox credentials either.

It still runs the same six-element validation as a real adapter, so a payload that would be
rejected by a state is rejected here too.
"""

from __future__ import annotations

from typing import Any

from careos.integrations.evv.base import (
    EVVPayload,
    EVVTransmissionAdapter,
    TransmissionOutcome,
    TransmissionResult,
)


class LoopbackAdapter(EVVTransmissionAdapter):
    adapter_key = "loopback"
    aggregator_name = "Loopback (development only)"

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        sandbox: bool = True,
        outcome: TransmissionOutcome = TransmissionOutcome.accepted,
    ) -> None:
        super().__init__(config=config, sandbox=sandbox)
        self.outcome = outcome
        #: Everything transmitted, so tests can assert on the exact wire content.
        self.submissions: list[dict[str, Any]] = []

    async def submit(self, payload: EVVPayload) -> TransmissionResult:
        payload.validate()
        snapshot = payload.as_canonical_snapshot()
        self.submissions.append(snapshot)
        return TransmissionResult(
            outcome=self.outcome,
            aggregator_reference=f"loopback-{payload.visit_id}",
            raw_response={"echo": snapshot},
            error_message=None if self.outcome is not TransmissionOutcome.rejected else "rejected",
        )
