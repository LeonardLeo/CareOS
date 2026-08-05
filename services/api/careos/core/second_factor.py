"""Enrolling, proving, and replacing a second factor — for any account that has one.

`careos.core.mfa` is the RFC 6238 arithmetic and nothing else: a secret, a counter, a
truncation rule. This module is the *stateful* half — the part that decides what happens to
the columns on an account when someone enrols, when they present a code, and when they
replace a device. It was written when a second kind of account appeared.

**Why it is shared rather than copied.** CareOS now has two identities that carry a second
factor: `app_user`, and `platform_operator` for the CareOS operator console. Every one of the
properties below took a defect to arrive at, and two copies of them would eventually differ
on exactly one — which would then be the one that mattered:

* Enrolment does **not** set `mfa_enrolled`. It is finished when the user has produced a
  code, so a tab closed after scanning cannot lock somebody out of an account whose only
  route back in is the requirement they now fail.
* Re-enrolling over a live factor **requires proving the factor in force**. Without it a
  stolen session is enough to move somebody's MFA onto the thief's device and collect ten
  fresh recovery codes on the way. This was found by exercising the running API, not by
  reading the code.
* A code is **single-use inside its own window**, because a code read over a shoulder that
  still works is a thirty-second password.
* A recovery code is consumed by reassigning the list, not by mutating it. SQLAlchemy does
  not track in-place mutation of a plain JSONB list, so `remaining.remove(...)` alone leaves
  the code usable forever and nothing looks wrong.

The account is passed as a structural type rather than a base class. Both models already had
these five columns for their own reasons, and a shared mixin would have coupled the tenant
user table to the platform operator table in the metadata for no gain.
"""

from __future__ import annotations

from typing import Protocol

from careos.core import mfa
from careos.core.crypto import decrypt_field, encrypt_field
from careos.core.errors import MFAInvalidCodeError, MFARequiredError, ValidationError
from careos.core.security import hash_password, verify_password


class SecondFactorHolder(Protocol):
    """Any account row carrying a TOTP factor.

    Satisfied by `careos.modules.agency.models.AppUser` and
    `careos.modules.platform.models.PlatformOperator`.
    """

    mfa_enrolled: bool
    mfa_secret_encrypted: bytes | None
    mfa_last_counter: int | None
    mfa_recovery_hashes: list[str]


def issue(holder: SecondFactorHolder, *, account: str) -> tuple[str, str, list[str]]:
    """Mint a secret and recovery codes onto `holder`. Returns (secret, otpauth URI, codes).

    Writes to the instance and does not flush: the caller owns the transaction, and the audit
    row that goes with this has to land in it. `mfa_enrolled` is cleared rather than set —
    see the module docstring.
    """
    secret = mfa.generate_secret()
    recovery_codes = mfa.generate_recovery_codes()

    holder.mfa_secret_encrypted = encrypt_field(secret)
    # Hashed with the password hasher, because each of these is a credential that skips the
    # second factor entirely. Normalized first so the stored hash matches what a person types.
    holder.mfa_recovery_hashes = [
        hash_password(mfa.normalize_recovery_code(code)) for code in recovery_codes
    ]
    holder.mfa_last_counter = None
    holder.mfa_enrolled = False
    return secret, mfa.provisioning_uri(secret, account=account), recovery_codes


def confirm(holder: SecondFactorHolder, code: str) -> None:
    """Finish enrolment by proving a code, or raise."""
    secret = decrypt_field(holder.mfa_secret_encrypted)
    if secret is None:
        raise ValidationError("Start enrolment before confirming it.")

    counter = mfa.verify_code(secret, code, last_counter=holder.mfa_last_counter)
    if counter is None:
        raise MFAInvalidCodeError("That code is not valid. Check your authenticator app's clock.")

    holder.mfa_enrolled = True
    holder.mfa_last_counter = counter


def consume_recovery_code(holder: SecondFactorHolder, code: str) -> bool:
    """Spend one recovery code, or return False.

    Verified against every stored hash rather than by lookup, because they are hashed — which
    is why this costs a linear scan of ten Argon2 verifications and is only reached after a
    TOTP code has already failed.
    """
    supplied = mfa.normalize_recovery_code(code)
    remaining = list(holder.mfa_recovery_hashes or [])
    for stored in remaining:
        if verify_password(supplied, stored):
            remaining.remove(stored)
            holder.mfa_recovery_hashes = remaining
            return True
    return False


def assert_satisfied(holder: SecondFactorHolder, *, code: str | None) -> None:
    """Check the second factor, or raise.

    Called after the password verifies, so every branch here is reachable only by someone who
    already holds valid credentials — which is what makes saying "the code is wrong" safe.

    An account with no factor enrolled passes. Whether that is *acceptable* is the caller's
    question, not this function's: the tenant side answers it with `MFA_REQUIRED_ROLES` and a
    configuration flag, and the platform console answers it unconditionally.
    """
    if not holder.mfa_enrolled:
        return

    secret = decrypt_field(holder.mfa_secret_encrypted)
    if secret is None:
        # Enrolled with no secret should be impossible. Failing closed rather than waving it
        # through: the alternative is that a corrupted row silently downgrades an account to
        # single-factor.
        raise MFARequiredError("Multi-factor authentication is not usable on this account.")

    if not code:
        raise MFARequiredError("Enter the code from your authenticator app.")

    counter = mfa.verify_code(secret, code, last_counter=holder.mfa_last_counter)
    if counter is not None:
        holder.mfa_last_counter = counter
        return

    if consume_recovery_code(holder, code):
        return

    raise MFAInvalidCodeError("That code is not valid.")


__all__ = [
    "SecondFactorHolder",
    "assert_satisfied",
    "confirm",
    "consume_recovery_code",
    "issue",
]
