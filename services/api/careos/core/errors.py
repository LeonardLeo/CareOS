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


class PermissionDeniedError(CareOSError):
    status_code = 403
    code = "PERMISSION_DENIED"


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
