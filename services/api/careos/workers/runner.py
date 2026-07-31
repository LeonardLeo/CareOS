"""The process that actually runs the background jobs.

Until this existed, `evv_transmission.run_once`, `webhook_delivery.drain_agency`, and
`credential_expiry.announce_expiring_credentials` were tested coroutines that nothing called.
Every one of them was written, reviewed, and green in CI — and in a deployment an EVV record
would have sat untransmitted until a state audit found it, and a webhook subscription would
have received nothing at all. A queue with no consumer is not a queue, it is a table.

**Deliberately not Celery, RQ, or a cron container.** The work is three coroutines that take an
`agency_id`; the missing part was a loop, a clock, and a way to not do it twice. A broker would
add a second datastore to operate, a serialization format to version, and a failure mode
("the queue is backed up") that this system does not otherwise have — the durable queue is
already in Postgres, which is where the outbox pattern put it on purpose. When a job needs
fan-out across machines or a retry policy of its own, that is the moment to reach for a broker,
not before.

**Scale across agencies, not within one.** Each job takes an advisory lock per (job, agency),
so N workers divide the tenants between them and no two ever work the same agency's queue at
the same moment. `SKIP LOCKED` in the workers themselves is the second line — it stops two
workers sending one delivery twice — but the lock is what makes a read-then-write job like the
credential announcer safe, and it is why adding a replica is a capacity decision rather than a
correctness one.

**One agency's failure is one agency's failure.** Every job is wrapped per agency. An agency
whose EVV adapter is misconfigured must not stop the other four hundred from transmitting, and
"the worker died at 3am on a bad row" is the failure mode this shape exists to prevent.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select

from careos.config import get_settings
from careos.core import metrics
from careos.db import models as _all_models  # noqa: F401  (registers every mapper; see below)
from careos.db.session import advisory_job_lock, dispose_engines, privileged_session
from careos.modules.agency.models import Agency
from careos.workers import (
    credential_expiry,
    evv_transmission,
    screening,
    webhook_delivery,
)

# `careos.db.models` is imported for its side effect, exactly as `careos.main` does it. The
# jobs write rows whose foreign keys point at tables this module never names — a webhook
# delivery references `agency` — and SQLAlchemy resolves those against whatever is registered
# at flush time. Importing only what is called here is enough to start and enough to pass a
# test, and raises `NoReferencedTableError` on the first write in a deployment.

logger = structlog.get_logger(__name__)

#: How long a single agency's job may take before it is abandoned for this tick.
#:
#: Without it one unreachable receiver holds the whole loop: webhook delivery gives each
#: request ten seconds, and a batch of a hundred against a black-holing endpoint is a
#: seventeen-minute tick during which no other agency is served. The job's own state is
#: transactional, so a cancelled pass rolls back and retries next tick rather than half-writing.
JOB_TIMEOUT_SECONDS = 120.0


@dataclass(slots=True)
class Job:
    """One unit of recurring work, and how often it should happen."""

    name: str
    interval_seconds: float
    run: Callable[[uuid.UUID], Awaitable[object]]
    #: Monotonic time of the last run. Never run means "due now".
    last_run: float | None = None

    def is_due(self, now: float) -> bool:
        return self.last_run is None or (now - self.last_run) >= self.interval_seconds


@dataclass
class TickSummary:
    agencies: int = 0
    ran: int = 0
    skipped_locked: int = 0
    failed: int = 0
    timed_out: int = 0
    jobs: list[str] = field(default_factory=list)


async def _agency_ids() -> list[uuid.UUID]:
    """Every tenant, in creation order.

    The third legitimate use of the privileged pool, alongside login and provisioning: a worker
    has no tenant until it picks one, so enumerating them cannot happen under RLS. It reads
    `agency.id` and nothing else — the job it hands each id to runs on the ordinary tenant
    session, where RLS applies as usual.
    """
    async with privileged_session() as session:
        rows = await session.execute(select(Agency.id).order_by(Agency.created_at))
        return list(rows.scalars())


async def _run_job_for_agency(job: Job, agency_id: uuid.UUID, summary: TickSummary) -> None:
    lock_key = f"careos.worker.{job.name}.{agency_id}"
    async with advisory_job_lock(lock_key) as acquired:
        if not acquired:
            # Another worker has this agency. Not an error and not worth logging at info —
            # with several replicas it is the normal case for most agencies on most ticks.
            summary.skipped_locked += 1
            metrics.worker_job_runs_total.labels(job=job.name, outcome="skipped_locked").inc()
            return

        started = time.perf_counter()
        try:
            async with asyncio.timeout(JOB_TIMEOUT_SECONDS):
                result = await job.run(agency_id)
        except TimeoutError:
            summary.timed_out += 1
            metrics.worker_job_runs_total.labels(job=job.name, outcome="timeout").inc()
            logger.error(
                "worker.job_timeout",
                job=job.name,
                agency_id=str(agency_id),
                seconds=JOB_TIMEOUT_SECONDS,
            )
            return
        except Exception:
            # Caught, counted, and carried on from. The alternative is that one agency with a
            # bad row stops every other agency's work, which is how a background worker becomes
            # the thing that silently stopped weeks ago.
            summary.failed += 1
            metrics.worker_job_runs_total.labels(job=job.name, outcome="error").inc()
            logger.exception("worker.job_failed", job=job.name, agency_id=str(agency_id))
            return
        finally:
            metrics.worker_job_duration_seconds.labels(job=job.name).observe(
                time.perf_counter() - started
            )

        summary.ran += 1
        metrics.worker_job_runs_total.labels(job=job.name, outcome="ok").inc()
        logger.debug("worker.job_ran", job=job.name, agency_id=str(agency_id), result=str(result))


async def run_tick(jobs: list[Job], *, stop: asyncio.Event | None = None) -> TickSummary:
    """Run every job that is due, once per agency. Returns what happened.

    Exposed rather than buried in the loop so the test suite can drive one pass deterministically
    instead of racing a timer, and so an operator can run a single pass by hand.
    """
    summary = TickSummary()
    now = time.monotonic()
    due = [job for job in jobs if job.is_due(now)]
    if not due:
        return summary

    agency_ids = await _agency_ids()
    summary.agencies = len(agency_ids)
    summary.jobs = [job.name for job in due]

    for job in due:
        for agency_id in agency_ids:
            if stop is not None and stop.is_set():
                # Between agencies, so shutdown costs at most one agency's job rather than
                # killing a delivery mid-flight. `job.last_run` is deliberately left alone:
                # an interrupted pass is not a completed one.
                logger.info("worker.stopping_mid_tick", job=job.name)
                return summary
            await _run_job_for_agency(job, agency_id, summary)
        job.last_run = time.monotonic()
        metrics.worker_last_run_timestamp.labels(job=job.name).set(time.time())

    return summary


def default_jobs() -> list[Job]:
    """The five jobs, with the cadence each one's failure mode argues for.

    EVV transmission is the tightest: `06_Compliance_and_Regulatory_Requirements.md` treats
    late transmission as a compliance problem, and the adapter has its own backoff, so polling
    often costs little and losing time costs a state filing. Webhook delivery matches it — a
    receiver waiting minutes for "the visit was acknowledged" is a receiver that will poll the
    API instead, which is the load this was meant to remove.

    The credential announcer runs daily because it is a calendar job: nothing changes about
    "expires in 12 days" between one minute and the next. It is safe to run more often — the
    `dedupe_on` key means a second run queues nothing — and that safety is what lets the
    schedule live in process memory rather than in a table. A restarting container re-runs it
    and no receiver notices.

    Screening splits into two because its halves share nothing but a vendor. Polling for
    verdicts runs every few minutes — a caregiver whose check cleared at 09:00 should be
    assignable before lunch — and its failure leaves a new hire unable to take publicly-funded
    work. Ordering re-screens is a daily calendar job, and its failure leaves an existing
    caregiver working against a clearance that has gone stale. One interval could not serve
    both.
    """
    settings = get_settings()
    return [
        Job(
            name="evv_transmission",
            interval_seconds=settings.worker_evv_interval_seconds,
            run=evv_transmission.run_once,
        ),
        Job(
            name="webhook_delivery",
            interval_seconds=settings.worker_webhook_interval_seconds,
            run=webhook_delivery.drain_agency,
        ),
        Job(
            name="credential_expiry",
            interval_seconds=settings.worker_credential_interval_seconds,
            run=credential_expiry.announce_expiring_credentials,
        ),
        Job(
            name="screening_poll",
            interval_seconds=settings.worker_screening_poll_interval_seconds,
            run=screening.poll_screening_results,
        ),
        Job(
            name="screening_rescreen",
            interval_seconds=settings.worker_screening_rescreen_interval_seconds,
            run=screening.order_screening_rescreens,
        ),
    ]


async def run_forever(
    jobs: list[Job] | None = None,
    *,
    stop: asyncio.Event | None = None,
    poll_seconds: float | None = None,
) -> None:
    """Tick until asked to stop.

    The loop sleeps the poll interval *after* a tick rather than trying to hold a fixed period.
    A tick that overruns therefore delays the next one instead of stacking a second pass on top
    of the first, which is the failure that turns a slow receiver into an unbounded pile of
    concurrent workers all fighting for the same rows.
    """
    jobs = jobs if jobs is not None else default_jobs()
    stop = stop if stop is not None else asyncio.Event()
    interval = poll_seconds if poll_seconds is not None else get_settings().worker_poll_seconds

    logger.info(
        "worker.started",
        jobs={job.name: job.interval_seconds for job in jobs},
        poll_seconds=interval,
    )
    while not stop.is_set():
        started = time.monotonic()
        summary = await run_tick(jobs, stop=stop)
        elapsed = time.monotonic() - started
        if summary.jobs:
            logger.info(
                "worker.tick",
                jobs=summary.jobs,
                agencies=summary.agencies,
                ran=summary.ran,
                skipped_locked=summary.skipped_locked,
                failed=summary.failed,
                timed_out=summary.timed_out,
                seconds=round(elapsed, 3),
            )
            if elapsed > interval:
                # Worth saying out loud: it means the worker is now the bottleneck, and the
                # numbers above say which job and how many agencies.
                logger.warning("worker.tick_overran", seconds=round(elapsed, 3), interval=interval)

        with contextlib.suppress(TimeoutError):
            # Sleeping on the stop event rather than on the clock, so SIGTERM is acted on
            # immediately instead of after a full interval — the difference between a
            # container restarting in a second and one being killed after a grace period.
            await asyncio.wait_for(stop.wait(), timeout=interval)

    logger.info("worker.stopped")


async def main() -> None:
    """Entry point: `python -m careos.workers.runner`."""
    settings = get_settings()
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # A container gets SIGTERM and then, some seconds later, SIGKILL. Handling it means
        # the current agency's job finishes and its transaction commits, rather than being
        # cut mid-delivery and redelivered on the next start.
        loop.add_signal_handler(sig, stop.set)

    if settings.worker_metrics_port:
        _serve_metrics(settings.worker_metrics_port, settings.worker_metrics_host)

    try:
        await run_forever(stop=stop)
    finally:
        await dispose_engines()


def _serve_metrics(port: int, host: str) -> None:
    """Expose this process's metrics for a collector.

    Its own port because this is its own process: the API's `/metrics` describes the API, and a
    worker that reported through it would be invisible whenever the API was the thing that was
    down. The alert that matters here — "nothing has transmitted EVV in an hour" — has to come
    from the process that would have done the transmitting.

    Guarded by the same bearer token as the API's endpoint, checked in constant time. An open
    metrics port is a description of a system's traffic and failure shape offered to anyone who
    asks, and the reasoning that made the API's endpoint token-protected does not stop applying
    because this one is easier to leave open.
    """
    import secrets as _secrets
    from http.server import HTTPServer
    from threading import Thread

    from prometheus_client.exposition import MetricsHandler

    expected = get_settings().metrics_token

    class TokenCheckingHandler(MetricsHandler.factory(metrics.REGISTRY)):  # type: ignore[misc]
        def do_GET(self) -> None:
            if expected:
                supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                if not _secrets.compare_digest(supplied, expected):
                    self.send_response(401)
                    self.end_headers()
                    return
            super().do_GET()

        def log_message(self, format: str, *args: object) -> None:
            """Silence per-scrape stdout lines; a scrape every 15s is not an event."""

    server = HTTPServer((host, port), TokenCheckingHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    logger.info("worker.metrics_listening", host=host, port=port, protected=bool(expected))


if __name__ == "__main__":
    asyncio.run(main())
