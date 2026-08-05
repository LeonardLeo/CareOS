"""Metrics, and the two things about them that can go wrong quietly.

The first is that they stop measuring — a counter wired to the wrong place looks identical to a
system with nothing to report, and the whole reason this exists is that a degraded rate limiter
and an unread EVV anomaly counter are invisible. So each signal is asserted against the event
that should produce it, not against the endpoint rendering.

The second is that they start leaking. Metrics outlive logs, are exported to systems with
looser access control than the database, and end up on dashboards that a lot of people can
see. A label carrying `agency_id` would put tenant activity in all of them and a `caregiver_id`
would put a person's working pattern there, so that is guarded structurally rather than by
review.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from careos.config import Settings, get_settings, validate_settings
from careos.core import metrics
from careos.modules.agency.models import Role
from tests.conftest import TenantFixture


def _value(name: str, **labels: str) -> float:
    return metrics.REGISTRY.get_sample_value(name, labels) or 0.0


# --- The exposition endpoint --------------------------------------------------------------


async def test_metrics_renders_prometheus_text(client) -> None:
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    # HELP lines rather than raw names, so a metric that exists but was never described — and
    # so means nothing to whoever reads the dashboard — does not satisfy this.
    assert "# HELP careos_http_requests_total" in body
    assert "# HELP careos_rate_limit_degraded" in body


async def test_metrics_requires_its_token_when_one_is_configured(client, monkeypatch) -> None:
    """A scraper is not a CareOS user, so the gate is a token rather than a role.

    Left open by default for local development; production cannot boot without one, which the
    test below pins.
    """
    monkeypatch.setenv("CAREOS_METRICS_TOKEN", "a-collector-token")
    get_settings.cache_clear()
    try:
        assert (await client.get("/metrics")).status_code == 401
        wrong = await client.get("/metrics", headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401
        right = await client.get("/metrics", headers={"Authorization": "Bearer a-collector-token"})
        assert right.status_code == 200
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_production_refuses_an_unauthenticated_metrics_endpoint() -> None:
    settings = Settings(
        environment="production",
        jwt_secret="a-real-production-secret-value",
        evv_use_sandbox=False,
        cors_allowed_origins=["https://app.careos.example"],
        rate_limit_backend="redis",
        metrics_token="",
        # Set so this test exercises the metrics gate rather than tripping over the MFA one:
        # `validate_settings` raises on the first unmet requirement, whichever that is.
        mfa_required=True,
        screening_adapter="vendor",
    )
    with pytest.raises(RuntimeError, match="CAREOS_METRICS_TOKEN"):
        validate_settings(settings)

    settings = settings.model_copy(update={"metrics_token": "set-in-the-secrets-manager"})
    assert validate_settings(settings) is not None


# --- No tenant or person in a label --------------------------------------------------------


def test_no_metric_carries_a_tenant_or_a_person() -> None:
    """The guarantee that keeps metrics exportable.

    Structural rather than a review note: this walks every collector actually registered, so a
    metric added later with an `agency_id` label fails here without anyone remembering the
    rule. `status` and `outcome` are fine; anything naming a tenant, a person, or a free-text
    identifier is not.
    """
    forbidden = {
        "agency",
        "agency_id",
        "caregiver",
        "caregiver_id",
        "client",
        "client_id",
        "email",
        "ip",
        "source_ip",
        "user",
        "user_id",
        "visit_id",
    }
    seen: list[tuple[str, str]] = []
    for collector in list(metrics.REGISTRY._collector_to_names):  # noqa: SLF001
        for label in getattr(collector, "_labelnames", ()):
            seen.append((getattr(collector, "_name", "?"), label))

    offenders = [(m, label) for m, label in seen if label.lower() in forbidden]
    assert offenders == [], f"metrics labelled with a tenant or a person: {offenders}"


def test_route_labels_are_templates_so_cardinality_stays_bounded() -> None:
    """`/v1/visits/{visit_id}` is one series; the concrete path is one per visit.

    Two problems in one: unbounded cardinality is how a metrics backend falls over, and the
    identifiers in those paths are exactly what the label rule above exists to keep out.
    """
    offenders = [
        (name, labels["route"])
        for name, labels in _route_labels()
        if any(_looks_like_an_id(segment) for segment in labels["route"].split("/"))
    ]
    assert offenders == [], f"route labels carrying a concrete identifier: {offenders}"


def _looks_like_an_id(segment: str) -> bool:
    try:
        uuid.UUID(segment)
    except ValueError:
        return False
    return True


def _route_labels():
    for metric in metrics.REGISTRY.collect():
        for sample in metric.samples:
            if "route" in sample.labels:
                yield sample.name, sample.labels


# --- Each signal against the event that should produce it ----------------------------------


async def test_requests_are_counted_under_the_route_template(
    client, tenant_a: TenantFixture
) -> None:
    missing = uuid.uuid4()
    before = _value(
        "careos_http_requests_total", method="GET", route="/v1/clients/{client_id}", status="404"
    )
    response = await client.get(
        f"/v1/clients/{missing}", headers=tenant_a.headers(Role.owner_admin)
    )
    assert response.status_code == 404
    after = _value(
        "careos_http_requests_total", method="GET", route="/v1/clients/{client_id}", status="404"
    )
    assert after == before + 1


async def test_rate_limit_refusals_are_counted_by_tier(client, tenant_a: TenantFixture) -> None:
    """Refusals never reach the router, so only the middleware can count them."""
    from careos.core.ratelimit import RateLimitPolicy, get_rate_limiter

    limiter = get_rate_limiter()
    original = limiter.policy
    before = _value("careos_rate_limit_refusals_total", tier="standard")
    limiter.policy = RateLimitPolicy(
        standard_per_minute=1,
        auth_per_minute=1_000_000,
        auth_per_ip_per_minute=1_000_000,
        evv_anomaly_per_minute=1_000_000,
        signup_per_hour=1_000_000,
    )
    limiter.store.reset()
    try:
        headers = tenant_a.headers(Role.owner_admin)
        assert (await client.get("/v1/clients", headers=headers)).status_code == 200
        assert (await client.get("/v1/clients", headers=headers)).status_code == 429
    finally:
        limiter.policy = original
        limiter.store.reset()

    assert _value("careos_rate_limit_refusals_total", tier="standard") == before + 1


async def test_a_failed_commit_is_counted(client, tenant_a: TenantFixture, monkeypatch) -> None:
    """How often the database will not accept a write is the signal that it is in trouble."""
    original = AsyncSession.commit

    async def failing_commit(self: AsyncSession) -> None:
        if self.info.get("careos_request_unit_of_work"):
            raise RuntimeError("simulated commit failure")
        await original(self)

    before = _value("careos_request_commit_failures_total")
    monkeypatch.setattr(AsyncSession, "commit", failing_commit)
    response = await client.post(
        "/v1/clients",
        headers=tenant_a.headers(Role.owner_admin),
        json={
            "legal_name": f"Counted Failure {uuid.uuid4().hex[:8]}",
            "service_state": "NY",
            "primary_payer_type": "private_pay",
        },
    )
    assert response.status_code == 500
    assert _value("careos_request_commit_failures_total") == before + 1


async def test_the_degraded_gauge_tracks_the_shared_store() -> None:
    """The signal this whole increment was justified by.

    A limiter falling back to per-instance buckets keeps answering every request, so the gauge
    is the only outward evidence that the published ceiling is not the enforced one.
    """
    from redis.asyncio import Redis

    from careos.core.ratelimit import InMemoryRateLimitStore, RedisRateLimitStore

    metrics.rate_limit_degraded.set(0)
    unreachable = RedisRateLimitStore(
        Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.05),
        fallback=InMemoryRateLimitStore(),
    )
    await unreachable.consume("gauge", limit=10, window_seconds=60)
    assert _value("careos_rate_limit_degraded") == 1.0
    assert unreachable.degraded is True


async def test_anomalous_evv_volume_is_counted(tenant_a: TenantFixture) -> None:
    """Section 9 asks for detection in place of throttling, and detection nobody reads is not.

    The counter is one half of the response — the compliance-exception path is covered in
    `test_rate_limits.py`. Nothing is ever refused, so both signals have to reach somewhere a
    person looks.
    """
    from careos.core.ratelimit import RateLimiter, RateLimitPolicy

    limiter = RateLimiter(
        RateLimitPolicy(
            standard_per_minute=99,
            auth_per_minute=99,
            auth_per_ip_per_minute=99,
            evv_anomaly_per_minute=1,
            signup_per_hour=99,
        )
    )
    before = _value("careos_evv_anomalous_volume_total")
    assert await limiter.note_evv_volume(agency_id="a", caregiver_id="cg") is False
    assert await limiter.note_evv_volume(agency_id="a", caregiver_id="cg") is True
    assert _value("careos_evv_anomalous_volume_total") == before + 1
