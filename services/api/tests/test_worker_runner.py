"""The process that runs the background jobs.

Everything the workers do was already tested. What was not tested — because it did not exist —
is that anything calls them. These tests are about the loop: that it reaches every tenant, that
one agency's failure is not every agency's failure, that two workers do not do the same job at
once, and that it stops when asked.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from careos.db.session import advisory_job_lock, tenant_session
from careos.modules.agency.models import Role
from careos.modules.webhooks import service
from careos.modules.webhooks.models import DeliveryStatus, WebhookDelivery, WebhookEvent
from careos.workers import runner
from tests.conftest import TenantFixture


def _recording_job(name: str, *, interval: float = 0.0, fails: bool = False) -> tuple:
    """A job that records the agencies it was handed."""
    seen: list[uuid.UUID] = []

    async def run(agency_id: uuid.UUID) -> str:
        seen.append(agency_id)
        if fails:
            raise RuntimeError("this agency is broken")
        return "ok"

    return runner.Job(name=name, interval_seconds=interval, run=run), seen


async def test_a_tick_reaches_every_agency(
    tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    """The enumeration is the point: a per-agency worker with no list of agencies does nothing."""
    job, seen = _recording_job("reaches-everyone")

    summary = await runner.run_tick([job])

    assert tenant_a.agency_id in seen
    assert tenant_b.agency_id in seen
    assert summary.ran == summary.agencies >= 2
    assert summary.failed == 0


async def test_one_agency_failing_does_not_stop_the_others(
    tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    """The failure mode this shape exists to prevent.

    A worker that dies on a bad row stops working for every other tenant too, and the way you
    find out is that a state audit asks why three weeks of visits were never transmitted.
    """
    attempted: list[uuid.UUID] = []

    async def run(agency_id: uuid.UUID) -> str:
        attempted.append(agency_id)
        if agency_id == tenant_a.agency_id:
            raise RuntimeError("adapter misconfigured for this agency")
        return "ok"

    summary = await runner.run_tick([runner.Job("breaks-once", 0.0, run)])

    assert tenant_a.agency_id in attempted
    assert tenant_b.agency_id in attempted, "a failing agency stopped the loop"
    assert summary.failed == 1
    assert summary.ran == summary.agencies - 1


async def test_a_job_another_worker_holds_is_skipped(tenant_a: TenantFixture) -> None:
    """Two workers must not run one agency's job at the same time.

    `SKIP LOCKED` covers a queue of rows, but not a job that reads before it writes — the
    credential announcer checks for an existing delivery before queueing one, and two workers
    can both read "no" before either writes.
    """
    job, seen = _recording_job("contended")

    # Exactly what a second worker mid-job looks like from here.
    async with advisory_job_lock(f"careos.worker.contended.{tenant_a.agency_id}") as held:
        assert held, "could not take the lock; the test proves nothing"
        summary = await runner.run_tick([job])

    assert tenant_a.agency_id not in seen
    assert summary.skipped_locked >= 1

    # ...and once the other worker is done, the next tick picks it up.
    job.last_run = None
    await runner.run_tick([job])
    assert tenant_a.agency_id in seen


async def test_a_job_that_hangs_is_abandoned_for_this_tick(tenant_a: TenantFixture) -> None:
    """One unreachable receiver must not hold the loop for every other agency.

    Webhook delivery allows ten seconds per request, so a batch against a black-holing endpoint
    would otherwise be a tick nobody else is served during.
    """
    started = asyncio.Event()

    async def hangs(agency_id: uuid.UUID) -> str:
        started.set()
        await asyncio.sleep(3600)
        return "never"

    monkey_timeout = 0.2
    original = runner.JOB_TIMEOUT_SECONDS
    runner.JOB_TIMEOUT_SECONDS = monkey_timeout
    try:
        summary = await asyncio.wait_for(
            runner.run_tick([runner.Job("hangs", 0.0, hangs)]), timeout=30
        )
    finally:
        runner.JOB_TIMEOUT_SECONDS = original

    assert started.is_set()
    assert summary.timed_out >= 1
    assert summary.ran == 0


async def test_a_job_is_not_run_before_its_interval(tenant_a: TenantFixture) -> None:
    """Otherwise the daily credential announcer would run every fifteen seconds."""
    job, seen = _recording_job("hourly", interval=3600.0)

    await runner.run_tick([job])
    first = len(seen)
    assert first >= 1

    await runner.run_tick([job])
    assert len(seen) == first, "a job with an hour-long interval ran twice in one second"


async def test_stopping_ends_the_loop_without_waiting_out_the_interval(
    tenant_a: TenantFixture,
) -> None:
    """SIGTERM must not mean "killed thirty seconds later".

    The loop sleeps on the stop event rather than on the clock, which is the difference between
    a container that restarts in a second and one the orchestrator eventually kills.
    """
    job, _seen = _recording_job("quick", interval=0.0)
    stop = asyncio.Event()

    async def stop_soon() -> None:
        await asyncio.sleep(0.1)
        stop.set()

    # A poll interval far longer than the test would tolerate: if the loop slept on it rather
    # than on the event, this times out.
    await asyncio.gather(
        asyncio.wait_for(runner.run_forever([job], stop=stop, poll_seconds=300), timeout=15),
        stop_soon(),
    )


async def test_the_default_jobs_are_the_ones_that_exist() -> None:
    """A worker written but not wired into the runner is the defect this file exists for.

    An equality assertion rather than a subset one, in both directions: a job added to
    `careos.workers` and never registered here does nothing in a deployment, and a job
    registered here whose module was deleted crashes the runner on the first tick.
    """
    names = {job.name for job in runner.default_jobs()}
    assert names == {
        "evv_transmission",
        "webhook_delivery",
        "credential_expiry",
        "screening_poll",
        "screening_rescreen",
        "evv_reconciliation",
    }
    assert all(job.interval_seconds > 0 for job in runner.default_jobs())


async def test_the_runner_actually_delivers_a_queued_webhook(
    client, tenant_a: TenantFixture
) -> None:
    """End to end, and the whole reason this increment exists.

    Everything upstream of here was green while a deployment delivered nothing, because the
    coroutine that delivers was called by no process. This asserts the queue drains when the
    runner — not the test — is what calls it.
    """
    created = await client.post(
        "/v1/webhooks",
        headers=tenant_a.headers(Role.owner_admin),
        json={
            "url": "https://receiver.example.com/careos",
            "events": [WebhookEvent.evv_transmission_acknowledged.value],
        },
    )
    assert created.status_code == 201, created.text

    async with tenant_session(tenant_a.agency_id) as session:
        await service.enqueue(
            session,
            agency_id=tenant_a.agency_id,
            event=WebhookEvent.evv_transmission_acknowledged,
            payload={"evv_record_id": str(uuid.uuid4())},
        )

    async with tenant_session(tenant_a.agency_id) as session:
        queued = (await session.execute(_deliveries())).scalars().one()
        assert queued.status is DeliveryStatus.pending

    # One tick of the real job list. `receiver.example.com` does not answer, so the delivery
    # comes back failing rather than delivered — which is still proof the runner reached it:
    # before this, `attempts` stayed at zero forever.
    summary = await runner.run_tick(runner.default_jobs())
    assert "webhook_delivery" in summary.jobs

    async with tenant_session(tenant_a.agency_id) as session:
        attempted = (await session.execute(_deliveries())).scalars().one()
    assert attempted.attempts >= 1, "the runner did not attempt the queued delivery"
    assert attempted.status in {DeliveryStatus.failing, DeliveryStatus.delivered}


def _deliveries():
    from sqlalchemy import select

    return select(WebhookDelivery)


@pytest.mark.parametrize("job", runner.default_jobs())
def test_every_default_job_is_a_coroutine_taking_an_agency(job: runner.Job) -> None:
    """The contract the runner depends on, checked rather than assumed.

    A job added later with a different signature would fail at 3am on a schedule instead of
    here — the runner calls it inside a per-agency `except`, so a `TypeError` would be counted
    as that agency's failure and logged rather than raised.
    """
    import inspect

    assert inspect.iscoroutinefunction(job.run)
    parameters = list(inspect.signature(job.run).parameters)
    assert parameters and parameters[0] == "agency_id"


def test_the_runner_process_can_map_every_model_it_writes() -> None:
    """Importing the runner must be enough to configure the whole ORM.

    A subprocess, because in-process every other test has already imported the world. The
    runner writes rows whose foreign keys point at tables it never mentions — a webhook
    delivery references `agency` — and SQLAlchemy resolves those against whatever is
    registered at flush time. An import dropped from this process would raise
    `NoReferencedTableError` on the first write in production and never once in CI.

    Found by running the worker by hand against a real database, which is the argument for
    doing that at least once per increment.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import careos.workers.runner\n"
            "from sqlalchemy.orm import configure_mappers\n"
            "configure_mappers()\n",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "importing careos.workers.runner does not register every model it writes:\n"
        f"{result.stderr[-1500:]}"
    )
