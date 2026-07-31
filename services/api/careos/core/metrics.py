"""Metrics, so that failures which are invisible from the outside stop being invisible.

The specific gap this closes. Several things in this system degrade rather than break, which is
deliberate — a degraded system that keeps serving caregivers beats one that stops — but it means
the only evidence is a log line nothing collects:

* **A degraded rate limiter answers every request.** When Redis is unreachable the buckets fall
  back to per-instance ones, so the cluster enforces N times the published ceiling and nothing
  about a response says so.
* **The EVV anomaly counter never refuses anything.** Section 9 asks for abuse detection in
  place of throttling on clock-in, and detection that nobody reads is not detection.
* **EVV transmissions escalate to a human** who has to be told.
* **A failed commit** is now answered honestly, but how often it happens is the thing that says
  whether the database is in trouble.

Prometheus text format on a scrape endpoint, rather than pushing anywhere, because that is what
every collector already speaks and it adds no outbound dependency to a request path.

**Labels never carry tenant or person.** No `agency_id`, no `caregiver_id`, no client name.
Metrics are retained longer than logs, exported to systems with looser access control than the
database, and often visible to anyone with a dashboard — a per-agency label would put tenant
activity in all of them, and a per-caregiver one would put a person's working pattern there.
Route *templates* are used rather than paths for the same reason, and because
`/v1/visits/{visit_id}` as a label is one time series where the concrete path is unbounded
cardinality.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

#: A registry of our own rather than the process-global default. The global one is shared
#: mutable state: a second `create_app()` in the same interpreter — which the test suite does
#: constantly — would raise on duplicate registration, and the default registry also carries
#: platform collectors nobody asked for.
REGISTRY = CollectorRegistry()

requests_total = Counter(
    "careos_http_requests_total",
    "HTTP requests, by route template and outcome.",
    ["method", "route", "status"],
    registry=REGISTRY,
)

request_duration_seconds = Histogram(
    "careos_http_request_duration_seconds",
    "Wall time from the start of the request middleware to the response, including the commit.",
    ["method", "route"],
    # Tuned for this API rather than left at the library default: the interesting boundary is
    # a clock-in, which crosses the network from a phone and must feel instant, and the tail
    # that matters is a request slow enough for a caregiver to notice standing at a door.
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

rate_limit_refusals_total = Counter(
    "careos_rate_limit_refusals_total",
    "Requests refused with 429, by tier.",
    ["tier"],
    registry=REGISTRY,
)

rate_limit_degraded = Gauge(
    "careos_rate_limit_degraded",
    (
        "1 when the shared rate-limit store is unreachable and limits are being enforced "
        "per instance instead of per cluster."
    ),
    registry=REGISTRY,
)

commit_failures_total = Counter(
    "careos_request_commit_failures_total",
    "Requests whose transaction could not be committed and were answered with 500.",
    registry=REGISTRY,
)

evv_anomalous_volume_total = Counter(
    "careos_evv_anomalous_volume_total",
    (
        "Clock-in/out actions above the per-caregiver volume ceiling. Never refused — this "
        "counter is the whole of the response, which is why it needs to be collected."
    ),
    registry=REGISTRY,
)

evv_transmissions_total = Counter(
    "careos_evv_transmissions_total",
    "EVV records leaving the transmission worker, by outcome.",
    ["outcome"],
    registry=REGISTRY,
)

evv_escalations_total = Counter(
    "careos_evv_escalations_total",
    (
        "EVV records that exhausted their retries and now need a human. A non-zero rate here "
        "is a compliance problem, not a queue problem."
    ),
    registry=REGISTRY,
)

webhook_deliveries_total = Counter(
    "careos_webhook_deliveries_total",
    "Outbound webhook delivery attempts, by outcome.",
    ["outcome"],
    registry=REGISTRY,
)

webhook_subscriptions_disabled_total = Counter(
    "careos_webhook_subscriptions_disabled_total",
    (
        "Subscriptions turned off after repeated delivery failure. An agency whose integration "
        "has silently stopped is a support ticket that has not been raised yet."
    ),
    registry=REGISTRY,
)

sessions_rejected_total = Counter(
    "careos_sessions_rejected_total",
    "Access tokens refused, by reason — revoked sessions separated from ordinary expiry.",
    ["reason"],
    registry=REGISTRY,
)


def render() -> bytes:
    """The scrape body, in Prometheus text format."""
    return generate_latest(REGISTRY)


CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
