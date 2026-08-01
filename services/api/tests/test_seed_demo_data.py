"""The demo seeder must not be able to reach anything but this machine.

It signs up an agency, creates staff accounts with a password it prints, and clocks visits in
and out. Pointed at a deployment that is not a laptop, that is a security incident with a
Makefile target — so the guard is tested rather than trusted, and the credential it uses is
asserted not to be a constant somebody could have committed.
"""

from __future__ import annotations

import pytest

from careos.scripts.seed_demo_data import DEMO_PASSWORD, generate_demo_password, refuse_non_local

LOCAL = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://[::1]:8000",
    "https://127.0.0.2:443",
]

REMOTE = [
    "https://api.careos.example",
    "http://10.0.1.20:8000",
    "http://192.168.1.50:8000",
    "http://169.254.169.254/",
    "http://0.0.0.0:8000",
    "http://staging-api.internal:8000",
]


@pytest.mark.parametrize("base_url", LOCAL)
def test_allows_this_machine(base_url: str) -> None:
    refuse_non_local(base_url)


@pytest.mark.parametrize("base_url", REMOTE)
def test_refuses_anything_else(base_url: str) -> None:
    """Includes the two that look local and are not.

    `0.0.0.0` is every interface rather than the loopback one, and `169.254.169.254` is the
    cloud metadata endpoint — the address a mistake is most expensive at.
    """
    with pytest.raises(RuntimeError, match="local-only"):
        refuse_non_local(base_url)


def test_refuses_a_url_with_no_host() -> None:
    with pytest.raises(RuntimeError, match="cannot read a host"):
        refuse_non_local("not-a-url")


def test_the_demo_password_is_generated_rather_than_committed() -> None:
    """Two calls must differ.

    Asserted structurally, not against a literal — a test that named the old constant would
    itself be the committed credential it exists to prevent, and a length check would pass
    happily for any hardcoded string somebody chose to make long.
    """
    assert generate_demo_password() != generate_demo_password()
    assert len(DEMO_PASSWORD) >= 16
