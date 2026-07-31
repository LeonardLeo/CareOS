"""Time-based one-time passwords (RFC 6238) and single-use recovery codes.

`08_Security_Architecture.md` Section 1 requires MFA for owner/admin, clinical supervisor, and
billing/RCM. Enrolment was tracked from the first migration and enforced nowhere, which is a
column that describes an intention rather than a control.

**Written against the RFC rather than pulled in as a dependency.** TOTP is HMAC, a counter, and
a truncation rule — about thirty lines — and the risk of writing it is that a subtle mistake
makes codes that no authenticator app accepts. That risk is answered directly: the test suite
runs the published RFC 6238 test vectors, so what is verified is interoperability with Google
Authenticator and 1Password rather than self-consistency with this file.

**SHA-1, and deliberately.** RFC 6238 permits SHA-256 and SHA-512, and essentially no
authenticator app implements them — a secret provisioned with `algorithm=SHA256` silently
produces codes that never match in most apps. SHA-1's weakness is collision resistance, which
a 30-second HMAC over a counter does not depend on.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

#: Seconds per code. 30 is what every authenticator app assumes; changing it means every
#: enrolled user's app is wrong and nobody can tell you why.
STEP_SECONDS = 30

#: Digits in a code.
DIGITS = 6

#: Steps of clock drift accepted either side of now. One step is ±30 seconds, which covers a
#: phone whose clock is slightly off and a person who starts typing as a code expires. Wider
#: multiplies the window an intercepted code stays usable in; narrower rejects honest people.
DRIFT_STEPS = 1

#: How many recovery codes are issued at enrolment.
#:
#: They exist because the alternative to a lost phone is a support ticket against the identity
#: system — and for the agency's only owner/admin, an unrecoverable one. Shown once, stored
#: only as hashes.
RECOVERY_CODE_COUNT = 10


def generate_secret() -> str:
    """A new base32 TOTP secret, in the format an authenticator app expects."""
    # 20 bytes is the RFC's recommended length for HMAC-SHA1 and what every app handles.
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _code_for_counter(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    # Dynamic truncation, RFC 4226 Section 5.3: the low nibble of the last byte picks the
    # offset, and the high bit is masked off so the result is positive on every platform.
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFF_FFFF
    return str(truncated % (10**DIGITS)).zfill(DIGITS)


def current_counter(at: float | None = None) -> int:
    return int((time.time() if at is None else at) // STEP_SECONDS)


def code_at(secret: str, at: float | None = None) -> str:
    """The code an authenticator app is showing right now. Used by tests and by nothing else."""
    return _code_for_counter(secret, current_counter(at))


def verify_code(secret: str, code: str, *, last_counter: int | None = None) -> int | None:
    """Check a code and return the counter it matched, or None.

    Returning the counter rather than a boolean is what makes replay refusable: the caller
    stores it, passes it back as `last_counter`, and a code already used cannot be used again
    inside its own validity window. Without that, a code shoulder-surfed or read off a shared
    screen stays good for up to a minute — which is exactly how long an attacker needs.

    Compared in constant time. The comparison is against a six-digit number, so a timing oracle
    is worth little, but it costs nothing to not have one.
    """
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        return None

    now = current_counter()
    for counter in range(now - DRIFT_STEPS, now + DRIFT_STEPS + 1):
        if last_counter is not None and counter <= last_counter:
            # Already used, or older than one that was. Skipped rather than compared, so a
            # replayed code cannot succeed even if it is otherwise correct.
            continue
        if hmac.compare_digest(_code_for_counter(secret, counter), code):
            return counter
    return None


def provisioning_uri(secret: str, *, account: str, issuer: str = "CareOS") -> str:
    """The `otpauth://` URI an authenticator app reads from a QR code.

    Emitted as text as well as encoded, because a user pairing a device they cannot point a
    camera at — a desktop password manager, a second phone — needs the secret itself.
    """
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Human-transcribable single-use codes, shown once at enrolment.

    Grouped and drawn from an unambiguous alphabet: these get written on paper, and a code
    containing both `0` and `O` produces a support call at the worst possible moment.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def normalize_recovery_code(code: str) -> str:
    """Accept what a person typed: any case, with or without the dash."""
    return code.strip().upper().replace("-", "").replace(" ", "")
