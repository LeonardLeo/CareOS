"""The single error envelope defined in `05_API_Specification.md` Section 1.

Every failure the API emits — validation, authorization, domain rule, unhandled — comes
back in the same shape, so clients (mobile, admin web, and third-party integrators in
Phase 3 Epic 3.6) parse one structure rather than several.
"""

from __future__ import annotations

from typing import Any


class CareOSError(Exception):
    """Base for errors that map onto an HTTP response.

    `code` is a stable machine-readable identifier. Treat it as part of the API contract:
    clients branch on it, so renaming one is a breaking change under the versioning policy
    in `05_API_Specification.md` Section 8.
    """

    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_envelope(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class ValidationError(CareOSError):
    status_code = 422
    code = "VALIDATION_ERROR"


class AuthenticationError(CareOSError):
    status_code = 401
    code = "AUTHENTICATION_REQUIRED"


class AccountInactiveError(AuthenticationError):
    """Correct credentials, but the account is disabled or not yet activated.

    A separate code rather than a separate message, because a client that branches on the text
    of an error is a client that breaks when the text is improved. It exists so a sign-in screen
    can say "this account has been disabled — contact your administrator" instead of "invalid
    email or password", which sends someone to reset a password that was never the problem.

    Reaching this discloses nothing an attacker did not already have: the password is verified
    first, so only somebody holding valid credentials is ever told the account is inactive.
    """

    code = "ACCOUNT_INACTIVE"


class PermissionDeniedError(CareOSError):
    status_code = 403
    code = "PERMISSION_DENIED"


class MFAEnrolmentRequiredError(CareOSError):
    """The caller's role requires MFA and they have not finished enrolling.

    403 rather than 401: the credentials were accepted and the session is real. What is
    missing is a step the user can take themselves, and a client that treated this as an
    authentication failure would send them back to a login screen that would let them in
    again and land here once more.
    """

    status_code = 403
    code = "MFA_ENROLMENT_REQUIRED"


class MFARequiredError(AuthenticationError):
    """Correct password, and the account has MFA — no code was supplied.

    Reached only after the password verifies, so it discloses nothing to someone guessing.
    Separate from `AUTHENTICATION_REQUIRED` so a sign-in screen can ask for the code instead
    of telling the user their password was wrong, which it was not.

    **Not a failed sign-in attempt.** It is the first half of a normal two-step sign-in: the
    client cannot know an account is enrolled until it tries. Recording it as a failure would
    write one "login failed" row per person per day and make the real ones unfindable.
    """

    code = "MFA_REQUIRED"


class MFAInvalidCodeError(MFARequiredError):
    """A code was supplied and it was wrong.

    The same wire code as its parent, so a client has one branch to write — asking for the code
    again is the right response either way. Distinct as a Python type because the server needs
    to tell them apart: somebody holding a valid password and guessing at codes is exactly the
    event the audit log and the brute-force limiter exist for.
    """


class NotFoundError(CareOSError):
    status_code = 404
    code = "NOT_FOUND"


class RateLimitExceededError(CareOSError):
    """Too many requests (`05_API_Specification.md` Section 9).

    Carries `retry_after` separately from `details` because it also becomes a `Retry-After`
    header — a client that has to parse the body to learn when to come back will mostly not
    bother, and will retry immediately instead.
    """

    status_code = 429
    code = "RATE_LIMIT_EXCEEDED"

    def __init__(self, message: str, retry_after: int, details: dict[str, Any] | None = None):
        super().__init__(message, details)
        self.retry_after = retry_after


class ConflictError(CareOSError):
    status_code = 409
    code = "CONFLICT"


class IdempotencyKeyRequiredError(CareOSError):
    status_code = 400
    code = "IDEMPOTENCY_KEY_REQUIRED"


class ComplianceGateError(CareOSError):
    """A hard compliance gate refused the operation.

    Distinct from `PermissionDeniedError` on purpose: this is not "you lack the role", it
    is "this action would violate a regulatory constraint regardless of who you are".
    Scheduling an excluded caregiver onto a Medicaid-billed visit (PRD US-1.3.2) is the
    canonical case. These are never downgraded to warnings.
    """

    status_code = 422
    code = "COMPLIANCE_GATE_FAILED"


class EVVTransmissionError(CareOSError):
    status_code = 502
    code = "EVV_TRANSMISSION_FAILED"


class CommitFailedError(CareOSError):
    """The request's work could not be made durable.

    Distinct from a bare 500 because the client can act on it: the message states that nothing
    was changed, which is true — the transaction is rolled back — so retrying is safe and, for
    an idempotent write, is the right response.

    It exists at all because the commit used to happen after the response was sent, where a
    failure had no status code left to occupy and the client was told the write had succeeded.
    """

    status_code = 500
    code = "COMMIT_FAILED"
