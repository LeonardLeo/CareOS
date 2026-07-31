"""Multi-factor authentication (`08_Security_Architecture.md` Section 1).

`mfa_enrolled` existed from the first migration and nothing ever set it or read it. Section 1
does not say "recommended" for owner/admin, clinical supervisor, and billing/RCM — it says
required — and those are the roles that can read every client record in the tenant and export
the lot, so a stolen password for one of them is a reportable breach.

Three things are being checked here, in order of how badly they fail:

1. **The codes are real TOTP.** A hand-written implementation that is subtly wrong produces an
   enrolment flow where nobody's authenticator app ever works, and the only symptom is users
   saying "it says the code is invalid". The published RFC vectors settle it.
2. **Single use, both kinds.** A code that survives its own use is a static password with extra
   steps, and a recovery code that survives is a permanent one written on paper.
3. **The requirement is actually enforced**, centrally, and cannot be laundered away through
   the refresh endpoint.
"""

from __future__ import annotations

import base64
import time
import uuid

import pytest

from careos.config import get_settings
from careos.core import mfa
from careos.db.session import tenant_session
from careos.modules.agency.models import AppUser, Role
from careos.modules.audit.models import AuditLog
from tests.conftest import TenantFixture

PASSWORD = "a-sufficiently-long-password"


def _next_code(secret: str) -> str:
    """The code for the *next* window.

    Needed because single-use is enforced across enrolment and login alike: the code spent
    confirming enrolment cannot then sign the user in, and both live in the same thirty-second
    window. A code one step ahead is inside the drift allowance and past the stored counter, so
    it is what a person reading their phone a moment later would type. This is also why the
    confirm endpoint hands back a session rather than telling the user to sign in again.
    """
    return mfa.code_at(secret, at=time.time() + mfa.STEP_SECONDS)


# --- The algorithm ---------------------------------------------------------------------------


#: RFC 6238 Appendix B, the SHA-1 rows. The seed is the ASCII string "12345678901234567890".
#:
#: These are the reason this file can claim interoperability rather than self-consistency: any
#: implementation that reproduces them is the one Google Authenticator, 1Password, and Authy
#: implement. A test that only checked `verify(generate())` would pass on an implementation
#: that agreed with nothing in the world.
RFC_6238_SHA1_VECTORS = [
    (59, "287082"),
    (1111111109, "081804"),
    (1111111111, "050471"),
    (1234567890, "005924"),
    (2000000000, "279037"),
    (20000000000, "353130"),
]


@pytest.mark.parametrize(("unix_time", "expected"), RFC_6238_SHA1_VECTORS)
def test_codes_match_the_rfc_6238_test_vectors(unix_time: int, expected: str) -> None:
    seed = base64.b32encode(b"12345678901234567890").decode()
    assert mfa.code_at(seed, at=unix_time) == expected


def test_a_code_is_accepted_within_the_drift_window_and_not_outside_it() -> None:
    """A phone's clock is never exactly right, and nobody types six digits instantly."""
    secret = mfa.generate_secret()
    now = time.time()

    assert mfa.verify_code(secret, mfa.code_at(secret, at=now)) is not None
    assert mfa.verify_code(secret, mfa.code_at(secret, at=now - mfa.STEP_SECONDS)) is not None
    assert mfa.verify_code(secret, mfa.code_at(secret, at=now + mfa.STEP_SECONDS)) is not None

    # Two steps out is a minute of drift: past what a working clock explains, and every extra
    # step doubles how long an intercepted code stays good.
    assert mfa.verify_code(secret, mfa.code_at(secret, at=now - 2 * mfa.STEP_SECONDS)) is None
    assert mfa.verify_code(secret, mfa.code_at(secret, at=now + 2 * mfa.STEP_SECONDS)) is None


def test_a_code_cannot_be_used_twice() -> None:
    """Without this a code is valid for its whole window however many times it is presented.

    Which means one glance over a shoulder, or one screenshot in a support chat, is one
    successful sign-in — and the second factor has become a thirty-second password.
    """
    secret = mfa.generate_secret()
    code = mfa.code_at(secret)

    counter = mfa.verify_code(secret, code)
    assert counter is not None
    assert mfa.verify_code(secret, code, last_counter=counter) is None


def test_malformed_input_is_refused_without_comparing() -> None:
    secret = mfa.generate_secret()
    for bad in ("", "12345", "1234567", "abcdef", "12 34 56 78"):
        assert mfa.verify_code(secret, bad) is None


def test_the_provisioning_uri_carries_the_parameters_an_app_reads() -> None:
    """An app that guesses `algorithm` or `period` guesses wrong for somebody."""
    secret = mfa.generate_secret()
    uri = mfa.provisioning_uri(secret, account="nurse@example.com")

    assert uri.startswith("otpauth://totp/CareOS%3Anurse%40example.com?")
    assert f"secret={secret}" in uri
    assert "algorithm=SHA1" in uri
    assert "digits=6" in uri
    assert "period=30" in uri


def test_recovery_codes_avoid_ambiguous_characters() -> None:
    """These get written on paper and read back over the phone."""
    for code in mfa.generate_recovery_codes():
        assert not set(code) & set("01OIl"), f"{code} contains a character people confuse"
        assert mfa.normalize_recovery_code(code.lower()) == mfa.normalize_recovery_code(code)


# --- Enrolment -------------------------------------------------------------------------------


async def _enrol(client, headers: dict[str, str]) -> tuple[str, list[str]]:
    """Run a user through enrolment; returns (secret, recovery codes)."""
    started = await client.post("/v1/auth/mfa/enroll", headers=headers)
    assert started.status_code == 200, started.text
    body = started.json()

    confirmed = await client.post(
        "/v1/auth/mfa/confirm",
        headers=headers,
        json={"code": mfa.code_at(body["secret"])},
    )
    assert confirmed.status_code == 200, confirmed.text
    # Confirming returns a session that satisfies the requirement, rather than asking the user
    # to sign in again with a code they have just spent.
    assert confirmed.json()["access_token"]
    return body["secret"], body["recovery_codes"]


async def test_enrolment_is_not_complete_until_a_code_is_proved(
    client, tenant_a: TenantFixture
) -> None:
    """The defect that would lock people out of their own accounts.

    Marking a user enrolled the moment a secret is issued means anyone who closes the tab
    before scanning is enrolled against a secret they do not have — and for a privileged role,
    that is an account which can now do nothing but fail the check it cannot satisfy.
    """
    headers = tenant_a.headers(Role.owner_admin)
    started = await client.post("/v1/auth/mfa/enroll", headers=headers)
    assert started.status_code == 200

    async with tenant_session(tenant_a.agency_id) as session:
        user = await session.get(AppUser, tenant_a.owner_id)
        assert user is not None
        assert user.mfa_secret_encrypted is not None, "the secret was not stored"
        assert user.mfa_enrolled is False, "issuing a secret must not count as enrolling"


async def test_the_secret_is_stored_encrypted(client, tenant_a: TenantFixture) -> None:
    """A second factor in plaintext is one a database compromise hands over with the hashes."""
    headers = tenant_a.headers(Role.owner_admin)
    started = await client.post("/v1/auth/mfa/enroll", headers=headers)
    secret = started.json()["secret"]

    async with tenant_session(tenant_a.agency_id) as session:
        user = await session.get(AppUser, tenant_a.owner_id)
        assert user is not None
        stored = user.mfa_secret_encrypted

    assert stored is not None
    assert secret.encode() not in stored, "the TOTP secret is readable in the database"


async def test_the_secret_and_recovery_codes_are_returned_once(
    client, tenant_a: TenantFixture
) -> None:
    """Same rule as the webhook signing secret: a value handed back twice leaks twice."""
    headers = tenant_a.headers(Role.owner_admin)
    secret, recovery_codes = await _enrol(client, headers)

    listed = await client.get(f"/v1/agencies/{tenant_a.agency_id}/users", headers=headers)
    assert listed.status_code == 200
    assert secret not in listed.text
    for code in recovery_codes:
        assert code not in listed.text


async def test_a_wrong_code_does_not_complete_enrolment(client, tenant_a: TenantFixture) -> None:
    headers = tenant_a.headers(Role.owner_admin)
    await client.post("/v1/auth/mfa/enroll", headers=headers)

    refused = await client.post("/v1/auth/mfa/confirm", headers=headers, json={"code": "000000"})
    assert refused.status_code == 401
    assert refused.json()["error"]["code"] == "MFA_REQUIRED"

    async with tenant_session(tenant_a.agency_id) as session:
        user = await session.get(AppUser, tenant_a.owner_id)
    assert user is not None and user.mfa_enrolled is False


async def test_confirming_without_starting_is_refused(client, tenant_a: TenantFixture) -> None:
    response = await client.post(
        "/v1/auth/mfa/confirm",
        headers=tenant_a.headers(Role.owner_admin),
        json={"code": "123456"},
    )
    assert response.status_code == 422


async def test_enrolment_is_audited_without_recording_the_secret(
    client, tenant_a: TenantFixture
) -> None:
    """An audit log is read by more people, and kept longer, than this response was."""
    headers = tenant_a.headers(Role.owner_admin)
    secret, recovery_codes = await _enrol(client, headers)

    async with tenant_session(tenant_a.agency_id) as session:
        rows = (await session.execute(_audit_rows())).scalars().all()

    actions = {row.action for row in rows}
    assert "user.mfa_enrolment_started" in actions
    assert "user.mfa_enrolled" in actions

    serialized = str([(row.before_state, row.after_state) for row in rows])
    assert secret not in serialized
    for code in recovery_codes:
        assert code not in serialized


def _audit_rows():
    from sqlalchemy import select

    return select(AuditLog)


# --- Signing in ------------------------------------------------------------------------------


async def _invite(client, tenant: TenantFixture, role: str) -> tuple[str, str]:
    email = f"{role}-{uuid.uuid4().hex[:8]}@mfa.example.com"
    response = await client.post(
        f"/v1/agencies/{tenant.agency_id}/users",
        headers=tenant.headers(Role.owner_admin),
        json={"email": email, "role": role, "initial_password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], email


async def test_an_enrolled_account_cannot_sign_in_with_a_password_alone(
    client, tenant_a: TenantFixture
) -> None:
    """The entire point of the feature, stated once."""
    user_id, email = await _invite(client, tenant_a, "clinical_supervisor")
    first = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert first.status_code == 200
    headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    secret, _codes = await _enrol(client, headers)

    without = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert without.status_code == 401
    assert without.json()["error"]["code"] == "MFA_REQUIRED"

    wrong = await client.post(
        "/v1/auth/login", json={"email": email, "password": PASSWORD, "mfa_code": "000000"}
    )
    assert wrong.status_code == 401

    correct = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": PASSWORD, "mfa_code": _next_code(secret)},
    )
    assert correct.status_code == 200, correct.text


async def test_a_wrong_password_with_a_right_code_is_still_refused(
    client, tenant_a: TenantFixture
) -> None:
    """The second factor is a second factor, not an alternative one."""
    _user_id, email = await _invite(client, tenant_a, "billing_rcm")
    first = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    secret, _codes = await _enrol(client, headers)

    response = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": "not-the-password", "mfa_code": _next_code(secret)},
    )
    assert response.status_code == 401
    # And it says nothing about the account: the password check failed first.
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


async def test_a_login_code_cannot_be_replayed(client, tenant_a: TenantFixture) -> None:
    """A code captured in flight must not sign anyone in a second time."""
    _user_id, email = await _invite(client, tenant_a, "clinical_supervisor")
    first = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    secret, _codes = await _enrol(client, headers)

    code = _next_code(secret)
    once = await client.post(
        "/v1/auth/login", json={"email": email, "password": PASSWORD, "mfa_code": code}
    )
    assert once.status_code == 200

    twice = await client.post(
        "/v1/auth/login", json={"email": email, "password": PASSWORD, "mfa_code": code}
    )
    assert twice.status_code == 401, "the same code signed in twice"


async def test_a_recovery_code_works_once_and_only_once(client, tenant_a: TenantFixture) -> None:
    """The lost-phone path. Without it, a lost phone is a support ticket at best.

    Single use matters more here than for a TOTP code: these do not expire, so one that
    survives its own use is a permanent second password on a piece of paper.
    """
    _user_id, email = await _invite(client, tenant_a, "billing_rcm")
    first = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    _secret, recovery_codes = await _enrol(client, headers)

    used = recovery_codes[0]
    once = await client.post(
        "/v1/auth/login", json={"email": email, "password": PASSWORD, "mfa_code": used}
    )
    assert once.status_code == 200, once.text

    twice = await client.post(
        "/v1/auth/login", json={"email": email, "password": PASSWORD, "mfa_code": used}
    )
    assert twice.status_code == 401, "a recovery code was accepted twice"

    # The others still work.
    another = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": PASSWORD, "mfa_code": recovery_codes[1].lower()},
    )
    assert another.status_code == 200, "recovery codes must accept the case a person types"


async def test_an_unenrolled_account_signs_in_normally(client, tenant_a: TenantFixture) -> None:
    """Enforcement is about privileged roles, not about breaking every caregiver's login."""
    _user_id, email = await _invite(client, tenant_a, "caregiver")
    response = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200


# --- Enforcement -----------------------------------------------------------------------------


@pytest.fixture
def mfa_enforced(monkeypatch):
    """Turn the requirement on, the way production has it."""
    monkeypatch.setenv("CAREOS_MFA_REQUIRED", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("CAREOS_MFA_REQUIRED", raising=False)
    get_settings.cache_clear()


async def test_an_unenrolled_privileged_user_can_only_reach_enrolment(
    client, tenant_a: TenantFixture, mfa_enforced: None
) -> None:
    """The requirement, enforced centrally rather than per endpoint.

    Not a refused login: the only way to enrol is an authenticated call made before enrolling,
    so refusing the session outright would make the requirement unsatisfiable.
    """
    _user_id, email = await _invite(client, tenant_a, "clinical_supervisor")
    signed_in = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert signed_in.status_code == 200, "an unenrolled privileged user must still get a session"
    headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}

    blocked = await client.get("/v1/clients", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "MFA_ENROLMENT_REQUIRED"

    # ...and the way out is open.
    allowed = await client.post("/v1/auth/mfa/enroll", headers=headers)
    assert allowed.status_code == 200


async def test_a_role_without_the_requirement_is_unaffected(
    client, tenant_a: TenantFixture, mfa_enforced: None
) -> None:
    """Section 1 names three roles. A scheduler is not one of them — yet.

    The same section says MFA "should become required" for schedulers, which is a change to
    `MFA_REQUIRED_ROLES` and nothing else.
    """
    _user_id, email = await _invite(client, tenant_a, "scheduler")
    signed_in = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}

    assert (await client.get("/v1/clients", headers=headers)).status_code == 200


async def test_enrolling_then_signing_in_again_gives_a_full_session(
    client, tenant_a: TenantFixture, mfa_enforced: None
) -> None:
    """End to end: blocked, enrol, sign in with a code, unblocked."""
    _user_id, email = await _invite(client, tenant_a, "clinical_supervisor")
    first = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    pending = {"Authorization": f"Bearer {first.json()['access_token']}"}
    assert (await client.get("/v1/clients", headers=pending)).status_code == 403

    started = await client.post("/v1/auth/mfa/enroll", headers=pending)
    secret = started.json()["secret"]
    confirmed = await client.post(
        "/v1/auth/mfa/confirm", headers=pending, json={"code": mfa.code_at(secret)}
    )
    assert confirmed.status_code == 200, confirmed.text

    # The session handed back by confirming is immediately usable — no second sign-in, and no
    # waiting out the window for the code that was just spent.
    headers = {"Authorization": f"Bearer {confirmed.json()['access_token']}"}
    assert (await client.get("/v1/clients", headers=headers)).status_code == 200


async def test_a_pending_session_cannot_be_refreshed_into_a_full_one(
    client, tenant_a: TenantFixture, mfa_enforced: None
) -> None:
    """The bypass this feature would otherwise ship with.

    `/auth/refresh` mints a new pair from a presented refresh token. If it carried the old
    token's MFA state forward — or defaulted to satisfied — an unenrolled privileged user could
    launder a pending session into full access through an endpoint that never asks for a code.
    """
    _user_id, email = await _invite(client, tenant_a, "billing_rcm")
    signed_in = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    refresh_token = signed_in.json()["refresh_token"]

    refreshed = await client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refreshed.status_code == 200
    headers = {"Authorization": f"Bearer {refreshed.json()['access_token']}"}

    blocked = await client.get("/v1/clients", headers=headers)
    assert blocked.status_code == 403, "refreshing laundered an unenrolled session into a full one"
    assert blocked.json()["error"]["code"] == "MFA_ENROLMENT_REQUIRED"


async def test_production_refuses_to_boot_without_the_requirement() -> None:
    """A control that can be left off by omission is a recommendation."""
    from careos.config import Settings, validate_settings

    base = {
        "environment": "production",
        "jwt_secret": "a-real-production-secret-value",
        "evv_use_sandbox": False,
        "cors_allowed_origins": ["https://admin.example.com"],
        "rate_limit_backend": "redis",
        "metrics_token": "a-real-token",
        "field_encryption_key": base64.b64encode(b"0" * 32).decode(),
    }

    with pytest.raises(RuntimeError, match="MFA_REQUIRED"):
        validate_settings(Settings(**base, mfa_required=False))

    validate_settings(Settings(**base, mfa_required=True))


async def test_a_caregiver_cannot_enrol_and_lock_themselves_out_of_the_phone(
    client, tenant_a: TenantFixture
) -> None:
    """The caregiver app has no field for a code, so enrolling would be a one-way door.

    Not a policy about caregivers and MFA — a guard about a client that cannot yet ask. The
    person who would discover it is a caregiver standing at a client's door unable to clock in,
    which is the highest-stakes surface in the product.
    """
    _user_id, email = await _invite(client, tenant_a, "caregiver")
    signed_in = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}

    refused = await client.post("/v1/auth/mfa/enroll", headers=headers)
    assert refused.status_code == 403
