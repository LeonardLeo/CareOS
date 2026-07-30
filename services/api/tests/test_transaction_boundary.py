"""The request's transaction commits before the client is told the request succeeded.

This is the guarantee the API did not have. `db_session` is a dependency with `yield`, and
FastAPI runs that teardown *after* the response is on the wire, so the commit used to happen
behind the client's back. Two things followed, and both are pinned here:

* A client could not reliably read its own write.
* A failed commit had no status code left to occupy, so the client was told the write had
  succeeded when it had been rolled back. On a clock-in that is a caregiver being told their
  visit was recorded when it was not.

The first test runs over a **real socket**, because the in-process ASGI transport the rest of
the suite uses cannot show the bug: it waits for the whole application coroutine — teardown
included — before handing the response back, which serializes exactly the race in question. A
test on that transport would have passed against the broken code.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import uvicorn
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from careos.main import create_app
from careos.modules.agency.models import Role
from tests.conftest import TenantFixture


@pytest.fixture
async def live_url():
    """The real app on a real TCP port, in this event loop.

    A socket rather than `ASGITransport` is the whole point — see the module docstring. In the
    same loop rather than a subprocess so it shares the engines the rest of the suite set up.
    """
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.05)
        else:  # pragma: no cover - the server failed to come up
            pytest.fail("the test server did not start")
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


async def test_a_client_can_read_its_own_write(
    live_url: str, tenant_a: TenantFixture, monkeypatch
) -> None:
    """Create a resource, then immediately use it. Over a socket, with no pause.

    This is the failure the caregiver-app end-to-end seed kept hitting in CI: `POST` returns
    201 and the very next call cannot see the row.

    The commit is deliberately slowed. Without that the test is a coin flip that a fast local
    Postgres nearly always wins — which is exactly why CI failed intermittently and a developer
    machine never did, and a regression test that only fails sometimes is not one.

    Two assertions, because either alone can be satisfied by a broken implementation:

    * **The POST took at least the injected delay.** That is what proves the commit happened
      inside the request. It also catches a regression that stops routing through
      `AsyncSession.commit` at all — as the original `async with session.begin()` did, which
      commits through SQLAlchemy's synchronous `SessionTransaction` and so slipped past this
      patch entirely, leaving the read to pass on luck.
    * **The immediate read found the row.** The behaviour anybody actually cares about.
    """
    original = AsyncSession.commit
    delay = 0.25

    async def slow_commit(self: AsyncSession) -> None:
        await asyncio.sleep(delay)
        await original(self)

    monkeypatch.setattr(AsyncSession, "commit", slow_commit)

    headers = tenant_a.headers(Role.owner_admin)
    async with AsyncClient(base_url=live_url, timeout=10.0) as http:
        started = asyncio.get_running_loop().time()
        created = await http.post(
            "/v1/clients",
            headers=headers,
            json={
                "legal_name": f"Read Own Write {uuid.uuid4().hex[:8]}",
                "service_state": "NY",
                "primary_payer_type": "private_pay",
            },
        )
        elapsed = asyncio.get_running_loop().time() - started
        assert created.status_code == 201, created.text
        client_id = created.json()["id"]

        # No sleep, no retry: the next request a real client would make.
        fetched = await http.get(f"/v1/clients/{client_id}", headers=headers)

    assert elapsed >= delay, (
        f"the response came back in {elapsed:.3f}s, faster than the {delay}s commit it is "
        "supposed to be waiting for — the write is being answered before it is durable"
    )
    assert fetched.status_code == 200, (
        "the write was answered before it was committed — a client cannot read its own "
        f"write: {fetched.status_code} {fetched.text}"
    )


async def test_a_failed_commit_is_reported_rather_than_hidden(
    client, tenant_a: TenantFixture, monkeypatch
) -> None:
    """The serious half. A commit that fails must not be answered with success.

    Runs on the in-process transport because this one is about *which* response the client
    gets, not about timing — and that is visible either way.
    """
    original = AsyncSession.commit

    async def failing_commit(self: AsyncSession) -> None:
        # Only the request's own unit of work. The revocation check opens its own session on
        # the way in and must still work, or the test would prove nothing about the commit.
        if self.info.get("careos_request_unit_of_work"):
            raise RuntimeError("simulated commit failure")
        await original(self)

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)

    legal_name = f"Never Committed {uuid.uuid4().hex[:8]}"
    response = await client.post(
        "/v1/clients",
        headers=tenant_a.headers(Role.owner_admin),
        json={
            "legal_name": legal_name,
            "service_state": "NY",
            "primary_payer_type": "private_pay",
        },
    )

    assert response.status_code == 500, (
        f"a rolled-back write was reported as {response.status_code} — this is the bug: the "
        "client is told a record exists that does not"
    )
    assert response.json()["error"]["code"] == "COMMIT_FAILED"
    # The message promises nothing was changed, so it has to be true.
    monkeypatch.undo()
    listed = await client.get("/v1/clients", headers=tenant_a.headers(Role.owner_admin))
    assert legal_name not in listed.text


async def test_a_handler_that_raises_leaves_nothing_behind(client, tenant_a: TenantFixture) -> None:
    """Rollback still happens on the exception path, which the refactor moved around.

    The commit moved to the middleware; the rollback stayed in the dependency, because an
    exception unwinds through the teardown before any response exists. If that had been moved
    too, a handler that wrote rows and then failed a compliance gate would leave them behind.
    """
    headers = tenant_a.headers(Role.owner_admin)
    # A care plan for a client that does not exist: the handler resolves the client, raises,
    # and any partial work must not survive.
    missing_client = uuid.uuid4()
    response = await client.post(
        f"/v1/clients/{missing_client}/care-plans",
        headers=headers,
        json={
            "authorized_tasks": [{"code": "bathing", "label": "Assist with bathing"}],
            "visit_frequency_rule": {"rrule": "FREQ=DAILY;COUNT=1", "start_hour": 9},
            "effective_start": "2026-08-01",
            "default_service_type_code": "T1019",
        },
    )
    assert response.status_code == 404

    # And the connection is usable afterwards, rather than left in a failed transaction.
    assert (await client.get("/v1/clients", headers=headers)).status_code == 200
