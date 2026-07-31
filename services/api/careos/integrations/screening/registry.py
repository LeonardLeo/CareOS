"""Selects the screening adapter.

Takes the EVV registry's stance rather than the routing registry's: it raises when nothing
usable is configured instead of falling back.

The difference is what a wrong answer costs. An unavailable routing provider degrades the
quality of a scheduling suggestion, so haversine is a reasonable default. An unavailable
screening provider that silently defaults to something would be deciding whether a caregiver
may be assigned to Medicaid-billed work — and the only default that is not a false-claims
exposure is "no verdict", which is what a raise produces.

The loopback adapter is registered but refused outside local and test environments, for the
same reason: it clears everyone whose name does not contain a marker string, which is exactly
the wrong behaviour in front of a real workforce.
"""

from __future__ import annotations

from careos.config import get_settings
from careos.core.errors import ScreeningUnavailableError
from careos.integrations.screening.adapters.loopback import LoopbackScreeningAdapter
from careos.integrations.screening.base import ScreeningAdapter

_ADAPTERS: dict[str, type[ScreeningAdapter]] = {
    LoopbackScreeningAdapter.adapter_key: LoopbackScreeningAdapter,
}

#: Adapters that must never run against a real workforce. Membership is by adapter key so a
#: vendor adapter added later is production-eligible by default and this list stays short.
_DEVELOPMENT_ONLY = {LoopbackScreeningAdapter.adapter_key}


def register_adapter(adapter_cls: type[ScreeningAdapter]) -> None:
    """Register an adapter class. Adding a background-check vendor starts here."""
    _ADAPTERS[adapter_cls.adapter_key] = adapter_cls


def available_adapter_keys() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


def get_screening_adapter() -> ScreeningAdapter:
    """Build the configured adapter, or raise.

    Raising is the safe failure here. A caregiver who cannot be screened stays `not_run` and
    therefore unassignable to publicly-funded visits, which is an operational problem an
    agency can see and escalate. The alternative failure — a screening that appears to have
    happened and did not — is invisible until a payer audit.
    """
    settings = get_settings()
    key = settings.screening_adapter
    adapter_cls = _ADAPTERS.get(key)
    if adapter_cls is None:
        raise ScreeningUnavailableError(
            f"No screening adapter registered under {key!r}",
            details={"configured": key, "available": list(available_adapter_keys())},
        )
    if key in _DEVELOPMENT_ONLY and settings.environment not in {"local", "test"}:
        raise ScreeningUnavailableError(
            f"The {key!r} screening adapter clears caregivers by fixture and must not run in "
            f"{settings.environment}",
            details={"configured": key, "environment": settings.environment},
        )
    return adapter_cls(sandbox=settings.screening_use_sandbox)
