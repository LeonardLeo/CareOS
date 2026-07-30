"""Token issuance/verification and password hashing.

`08_Security_Architecture.md` Section 1 calls for OAuth2/OIDC via a managed identity
provider rather than bespoke auth, and that remains the target: `AppUser.auth_provider_id`
is the seam for it. What lives here is the minimum needed to run and test the system before
that provider is provisioned — short-lived access tokens, refresh tokens, and Argon2id
password hashing. When the IdP lands, verification moves to its JWKS and the local password
path is deleted.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from careos.config import get_settings
from careos.core.errors import AuthenticationError
from careos.modules.agency.models import Role

_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller.

    `agency_id` comes from the token and from nowhere else. `05_API_Specification.md`
    Section 1 is explicit that a client-supplied tenant identifier is never used for
    tenant-scoping decisions, and this is where that rule is made structural: there is no
    code path that constructs a Principal from a request body or query parameter.
    """

    user_id: uuid.UUID
    agency_id: uuid.UUID
    role: Role
    #: Set for callers whose role is `caregiver`, so handlers can enforce the
    #: minimum-necessary rule (HIPAA; `08_Security_Architecture.md` Section 1) that a
    #: caregiver sees only visits assigned to them.
    caregiver_id: uuid.UUID | None = None
    #: When this token was issued, at microsecond resolution (from the `iat_us` claim, not the
    #: whole-second `iat`). Compared against the user's `sessions_revoked_at` watermark so a
    #: revoked session stops working immediately (`08_Security_Architecture.md` Section 6)
    #: rather than at the end of its 15-minute TTL.
    issued_at: datetime | None = None


def create_token(
    *,
    user_id: uuid.UUID,
    agency_id: uuid.UUID,
    role: Role,
    token_type: TokenType,
    caregiver_id: uuid.UUID | None = None,
) -> str:
    settings = get_settings()
    ttl = (
        settings.access_token_ttl_seconds
        if token_type == "access"
        else settings.refresh_token_ttl_seconds
    )
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "agency_id": str(agency_id),
        "role": role.value,
        "token_type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "jti": str(uuid.uuid4()),
        # Microsecond issue time, alongside the standard whole-second `iat`.
        #
        # Session revocation compares a token's issue time against a database timestamp that
        # has sub-second precision. With only `iat` — which is a NumericDate floored to the
        # second — a token issued 400ms *after* a revocation is indistinguishable from one
        # issued 400ms before it. Erring toward refusal then locks out the legitimate re-login
        # that follows an offboarding, and erring the other way leaves a sub-second window in
        # which a revoked token still works. Neither is acceptable, so the comparison is given
        # the precision it needs rather than a tie-break rule.
        "iat_us": int(now.timestamp() * 1_000_000),
    }
    if caregiver_id is not None:
        claims["caregiver_id"] = str(caregiver_id)
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, *, expected_type: TokenType = "access") -> Principal:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            # `iat_us` is required, not optional: session revocation compares against it, so a
            # token without one could not be evaluated and must not be accepted.
            options={"require": ["exp", "iat", "iat_us", "sub", "agency_id", "role", "token_type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid access token") from exc

    # A refresh token presented as an access token must be rejected. Without this check a
    # long-lived refresh token would authenticate ordinary requests, silently defeating the
    # short access-token TTL.
    if claims["token_type"] != expected_type:
        raise AuthenticationError(f"Expected a {expected_type} token")

    try:
        role = Role(claims["role"])
    except ValueError as exc:
        raise AuthenticationError("Token carries an unrecognized role") from exc

    caregiver_id = claims.get("caregiver_id")
    return Principal(
        user_id=uuid.UUID(claims["sub"]),
        agency_id=uuid.UUID(claims["agency_id"]),
        role=role,
        caregiver_id=uuid.UUID(caregiver_id) if caregiver_id else None,
        issued_at=datetime.fromtimestamp(claims["iat_us"] / 1_000_000, tz=UTC),
    )
