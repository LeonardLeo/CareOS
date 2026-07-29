"""Travel-time estimation behind one interface.

US-1.4.2 asks for schedules optimized on **drive time between consecutive visits**, not
straight-line distance. Those differ a lot in exactly the places home care operates: a client
across a river, a highway with no nearby crossing, or rush-hour traffic can turn two
map-miles into forty minutes.

`07_Integration_Specifications.md` Section 1 requires every external dependency to sit behind
an adapter so a vendor's shape never reaches domain logic. Routing is one of those, so it gets
the same treatment as EVV: the scheduler asks for a `TravelEstimate` and does not know or care
whether that came from a routing API or from arithmetic.

:class:`HaversineRoutingAdapter` is the default and is deliberately explicit that it is an
approximation — every estimate it returns carries ``is_estimate=True`` and a stated basis, so
a caller can surface the uncertainty rather than presenting a guess as a measurement.
"""

from __future__ import annotations

import abc
import math
from dataclasses import dataclass

#: Straight-line miles per hour, used to turn distance into a time estimate. Deliberately
#: conservative: home-care visits are mostly urban and suburban surface streets, not motorway.
DEFAULT_AVERAGE_SPEED_MPH = 25.0

#: Typical ratio of real road distance to straight-line distance. Around 1.2–1.4 in most US
#: metros; 1.3 is a middling default. This is a correction factor, not a measurement.
CIRCUITY_FACTOR = 1.3

_EARTH_RADIUS_MILES = 3958.8


@dataclass(frozen=True, slots=True)
class GeoPoint:
    lat: float
    lng: float


@dataclass(frozen=True, slots=True)
class TravelEstimate:
    """A distance and duration, plus how much to trust them."""

    miles: float
    minutes: float
    #: False only when a routing provider returned a real computed route.
    is_estimate: bool
    #: Short description of where the number came from, for display and for debugging.
    basis: str

    @property
    def hours(self) -> float:
        return self.minutes / 60.0


class RoutingAdapter(abc.ABC):
    """Base class for a travel-time provider."""

    adapter_key: str

    @abc.abstractmethod
    async def estimate(self, origin: GeoPoint, destination: GeoPoint) -> TravelEstimate: ...

    async def estimate_many(
        self, origin: GeoPoint, destinations: list[GeoPoint]
    ) -> list[TravelEstimate]:
        """One origin to many destinations.

        Overridden by providers offering a matrix endpoint — the scheduler ranks a whole
        roster against one visit, so issuing N separate calls would be both slow and
        needlessly expensive.
        """
        return [await self.estimate(origin, destination) for destination in destinations]


def haversine_miles(origin: GeoPoint, destination: GeoPoint) -> float:
    """Great-circle distance in miles."""
    phi1, phi2 = math.radians(origin.lat), math.radians(destination.lat)
    d_phi = math.radians(destination.lat - origin.lat)
    d_lambda = math.radians(destination.lng - origin.lng)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * _EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


class HaversineRoutingAdapter(RoutingAdapter):
    """Straight-line distance with a circuity correction.

    The default, and honest about its limits. It cannot know about rivers, one-way systems,
    bridges, or traffic, so its output is marked `is_estimate=True` throughout.

    Adequate for **ranking candidates relative to one another**, which is what Phase 1 uses it
    for: if three caregivers are 2, 8, and 40 minutes away, this ranks them correctly even
    though every individual number is wrong. It is *not* adequate for anything that quotes a
    traveltime to a person or pays them for it — replace it with a routing provider before
    travel time reaches a caregiver's screen or their timesheet.
    """

    adapter_key = "haversine"

    def __init__(
        self,
        *,
        average_speed_mph: float = DEFAULT_AVERAGE_SPEED_MPH,
        circuity_factor: float = CIRCUITY_FACTOR,
    ) -> None:
        if average_speed_mph <= 0:
            raise ValueError("average_speed_mph must be positive")
        self.average_speed_mph = average_speed_mph
        self.circuity_factor = circuity_factor

    async def estimate(self, origin: GeoPoint, destination: GeoPoint) -> TravelEstimate:
        straight_line = haversine_miles(origin, destination)
        road_miles = straight_line * self.circuity_factor
        return TravelEstimate(
            miles=road_miles,
            minutes=(road_miles / self.average_speed_mph) * 60.0,
            is_estimate=True,
            basis=(
                f"straight-line distance x{self.circuity_factor} circuity at "
                f"{self.average_speed_mph:.0f}mph — not a routed drive time"
            ),
        )
