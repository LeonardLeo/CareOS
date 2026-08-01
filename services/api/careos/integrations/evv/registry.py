"""Resolves a state to its EVV adapter.

The indirection is the point. `06_Compliance_and_Regulatory_Requirements.md` Section 1
notes that states periodically change EVV vendors; when that happens the fix is a row in
`evv_aggregator_ref`, not a change to the scheduling module.

The registry also enforces a compliance precondition that is easy to state and easy to skip:
an adapter may not transmit production data until it has been validated against that
vendor's sandbox (`07_Integration_Specifications.md` Section 2). That flag lives on the
reference row and is checked here, so no caller can forget it.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.config import get_settings
from careos.core.errors import EVVTransmissionError
from careos.integrations.evv.adapters.loopback import LoopbackAdapter
from careos.integrations.evv.adapters.rest import (
    HHAeXchangeAdapter,
    SandataAdapter,
    TellusAdapter,
)
from careos.integrations.evv.base import EVVTransmissionAdapter
from careos.modules.reference.models import EVVAggregatorRef

_ADAPTERS: dict[str, type[EVVTransmissionAdapter]] = {
    SandataAdapter.adapter_key: SandataAdapter,
    HHAeXchangeAdapter.adapter_key: HHAeXchangeAdapter,
    TellusAdapter.adapter_key: TellusAdapter,
    LoopbackAdapter.adapter_key: LoopbackAdapter,
}


def register_adapter(adapter_cls: type[EVVTransmissionAdapter]) -> None:
    """Register an adapter class. Adding a state's aggregator starts here."""
    _ADAPTERS[adapter_cls.adapter_key] = adapter_cls


def available_adapter_keys() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


async def resolve_for_state(session: AsyncSession, state_code: str) -> EVVTransmissionAdapter:
    """Build the adapter configured for `state_code`.

    Raises rather than falling back to a default. There is no safe default destination for
    EVV data: transmitting to the wrong aggregator is worse than not transmitting, because
    it looks like success.
    """
    ref = (
        await session.execute(
            select(EVVAggregatorRef).where(EVVAggregatorRef.state_code == state_code.upper())
        )
    ).scalar_one_or_none()

    if ref is None:
        raise EVVTransmissionError(
            f"No EVV aggregator is configured for state {state_code!r}",
            details={
                "state_code": state_code,
                "remediation": "Add a row to evv_aggregator_ref before operating in this state",
            },
        )

    adapter_cls = _ADAPTERS.get(ref.adapter_key)
    if adapter_cls is None:
        raise EVVTransmissionError(
            f"State {state_code!r} references unknown EVV adapter {ref.adapter_key!r}",
            details={"available": list(available_adapter_keys())},
        )

    settings = get_settings()
    use_sandbox = settings.evv_use_sandbox

    if not use_sandbox and not ref.sandbox_validated:
        raise EVVTransmissionError(
            f"Adapter {ref.adapter_key!r} for state {state_code!r} has not been validated "
            "against the vendor sandbox, so it must not transmit production data",
            details={
                "state_code": state_code,
                "adapter_key": ref.adapter_key,
                "remediation": (
                    "Validate against the vendor sandbox, then set "
                    "evv_aggregator_ref.sandbox_validated = true"
                ),
            },
        )

    # A development-only adapter must never be reachable in production, even if someone
    # points a production state row at it.
    if settings.is_production and ref.adapter_key == LoopbackAdapter.adapter_key:
        raise EVVTransmissionError(
            "The loopback EVV adapter cannot be used in production",
            details={"state_code": state_code},
        )

    return adapter_cls(config=ref.connection_config, sandbox=use_sandbox)
