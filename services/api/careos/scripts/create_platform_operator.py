"""Create the first CareOS platform operator.

    python -m careos.scripts.create_platform_operator \
        --email ops@careos.example --name "Ada Lovelace" --role platform_admin

**Why a script rather than an endpoint.** `POST /v1/platform/operators` requires an
authenticated `platform_admin`, and before the first operator exists there is nobody to be
one. The alternatives were a public bootstrap endpoint — which is a permanent hole that has
to be remembered and closed — or a seeded default account, which is a shipped credential.
This runs with database access, which whoever is standing the system up has and an attacker
on the internet does not.

It refuses to create a *second* operator without `--force`. Not paranoia: the failure this
prevents is somebody re-running the deploy step and quietly minting a second administrator
that nobody adds to an access review, and the ordinary way to add a colleague is the
console, which records who added them.

The password is read from `CAREOS_PLATFORM_OPERATOR_PASSWORD` or prompted for, never from
`argv` — a command line ends up in shell history, in `ps`, and in CI logs.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import func, select

from careos.db.session import dispose_engines, platform_session
from careos.modules.platform import service as platform_service
from careos.modules.platform.models import PlatformOperator, PlatformRole

#: Long, because this account can see every tenant's operational state and take an agency
#: offline, and because it is typed once and then stored in a password manager. The API
#: schema enforces the same floor for operators created through the console.
MIN_PASSWORD_LENGTH = 16


def _read_password() -> str:
    supplied = os.environ.get("CAREOS_PLATFORM_OPERATOR_PASSWORD")
    if supplied:
        return supplied
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Repeat: ")
    if first != second:
        raise SystemExit("Passwords did not match.")
    return first


async def _create(*, email: str, name: str, role: PlatformRole, force: bool) -> None:
    password = _read_password()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )

    async with platform_session() as session:
        existing = (
            await session.execute(select(func.count()).select_from(PlatformOperator))
        ).scalar_one()
        if existing and not force:
            raise SystemExit(
                f"{existing} platform operator(s) already exist. Add colleagues through the "
                "operator console so the creation is attributed and audited, or pass --force "
                "if you are deliberately bootstrapping a second one."
            )

        operator = await platform_service.create_operator(
            session,
            # No actor: this runs before any operator exists, which is the one case where
            # there is genuinely nobody to attribute the creation to. The audit row records
            # `bootstrap: true` rather than pointing at a fictional user.
            actor=None,
            email=email,
            display_name=name,
            role=role,
            initial_password=password,
        )

    print(f"Created platform operator {operator.email} ({role.value}).")
    print(
        "Multi-factor authentication is required and not yet enrolled. Sign in at "
        "/platform/login in the admin console; the session you get can reach the enrolment "
        "screen and nothing else until an authenticator is paired."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="Display name, shown beside audit rows")
    parser.add_argument(
        "--role",
        default=PlatformRole.platform_admin.value,
        choices=[r.value for r in PlatformRole],
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Create even though operators already exist",
    )
    args = parser.parse_args(argv)

    try:
        asyncio.run(
            _create(
                email=args.email,
                name=args.name,
                role=PlatformRole(args.role),
                force=args.force,
            )
        )
    finally:
        asyncio.run(dispose_engines())
    return 0


if __name__ == "__main__":
    sys.exit(main())
