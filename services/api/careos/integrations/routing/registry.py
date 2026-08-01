"""Selects the routing adapter.

Swapping in a real routing provider is a registration plus a config value, never a change to
the scheduling module — the same property the EVV registry provides.
"""

from __future__ import annotations

from careos.config import get_settings
from careos.integrations.routing.base import HaversineRoutingAdapter, RoutingAdapter

_ADAPTERS: dict[str, type[RoutingAdapter]] = {
    HaversineRoutingAdapter.adapter_key: HaversineRoutingAdapter,
}


def register_adapter(adapter_cls: type[RoutingAdapter]) -> None:
    _ADAPTERS[adapter_cls.adapter_key] = adapter_cls


def available_adapter_keys() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


def get_routing_adapter() -> RoutingAdapter:
    """Build the configured adapter.

    Falls back to haversine rather than raising when nothing is configured: an unavailable
    routing provider should degrade the *quality* of scheduling suggestions, not stop a
    scheduler from filling a shift. That is the opposite of the EVV registry's stance, and
    deliberately so — a wrong drive-time estimate is a worse suggestion, while a wrong EVV
    destination is a compliance failure that looks like success.
    """
    key = get_settings().routing_adapter
    adapter_cls = _ADAPTERS.get(key, HaversineRoutingAdapter)
    return adapter_cls()
