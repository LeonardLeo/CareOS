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
from careos.modules.platform.models import PlatformRole

_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]

#: Claim naming which kind of principal a token describes.
#:
#: Absent means tenant. That asymmetry is deliberate and matches how `mfa_pending` is
#: handled: a token minted before this claim existed is a tenant token, and reading its
#: absence as "platform" — or refusing it outright — would invalidate every session in flight
#: at deploy time for no security gain.
#:
#: A platform token carries no `agency_id`, so the two cannot be confused by accident. This
#: claim is what makes them impossible to confuse *deliberately*: `decode_token` refuses a
#: token that declares itself platform even if someone later adds an `agency_id` to one, and
#: `decode_platform_token` refuses anything that does not declare it.
PRINCIPAL_TYPE_CLAIM = "principal_type"
PLATFORM_PRINCIPAL_TYPE = "platform"


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
    #: Whether this session satisfies the MFA requirement for its role. False only for a user
    #: in an MFA-required role who has not finished enrolling — such a session can reach the
    #: enrolment endpoints and nothing else. Carried in the token rather than re-derived per
    #: request because it is a property of how the session was established: a token minted
    #: before enrolment must not silently become privileged when the user enrols elsewhere.
    mfa_satisfied: bool = True


@dataclass(frozen=True, slots=True)
class PlatformPrincipal:
    """An authenticated CareOS operator.

    Has no `agency_id`, and there is no code path that gives it one. That is the type-level
    statement of the design in `careos.modules.platform.models`: a platform operator is not
    a member of a tenant, so nothing about them can be used to scope a tenant query. A
    handler that receives one of these and reaches for `principal.agency_id` does not
    compile under mypy and does not run under Python.
    """

    operator_id: uuid.UUID
    role: PlatformRole
    #: Microsecond issue time, compared against `platform_operator.sessions_revoked_at`.
    issued_at: datetime | None = None
    #: Whether this session has proved a second factor. For an operator this is required
    #: unconditionally — there is no `CAREOS_MFA_REQUIRED` equivalent — so False means the
    #: session can reach the enrolment endpoints and nothing else.
    mfa_satisfied: bool = False


def create_token(
    *,
    user_id: uuid.UUID,
    agency_id: uuid.UUID,
    role: Role,
    token_type: TokenType,
    caregiver_id: uuid.UUID | None = None,
    mfa_satisfied: bool = True,
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
    if not mfa_satisfied:
        # Present only when false, so an old token — which cannot carry the claim — is read as
        # satisfied rather than as unenrolled. The alternative fails closed at first glance and
        # in fact fails *shut*: every session issued before this change would be locked out of
        # everything except enrolment, including sessions for roles MFA never applied to.
        claims["mfa_pending"] = True
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

    # A platform token must never resolve to a tenant principal. It carries no `agency_id`
    # today, so this is belt and braces — but the failure it guards against is the worst one
    # available here, a CareOS operator's token being handed to a tenant handler that then
    # scopes queries by whatever agency it can find.
    if claims.get(PRINCIPAL_TYPE_CLAIM) == PLATFORM_PRINCIPAL_TYPE:
        raise AuthenticationError("A platform token cannot be used on tenant endpoints")

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
        mfa_satisfied=not claims.get("mfa_pending", False),
    )


def create_platform_token(
    *,
    operator_id: uuid.UUID,
    role: PlatformRole,
    token_type: TokenType,
    mfa_satisfied: bool,
) -> str:
    """Mint a token for a CareOS operator.

    Signed with the same secret and the same algorithm as a tenant token, and carrying no
    `agency_id` at all. `mfa_satisfied` is written positively rather than as the tenant
    side's negative `mfa_pending`: there is no legacy token to stay compatible with here, and
    for the most privileged principal in the system the safe reading of a missing claim is
    "not satisfied" rather than "satisfied".
    """
    settings = get_settings()
    ttl = (
        settings.access_token_ttl_seconds
        if token_type == "access"
        else settings.refresh_token_ttl_seconds
    )
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(operator_id),
        PRINCIPAL_TYPE_CLAIM: PLATFORM_PRINCIPAL_TYPE,
        "role": role.value,
        "token_type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "jti": str(uuid.uuid4()),
        "iat_us": int(now.timestamp() * 1_000_000),
        "mfa_satisfied": mfa_satisfied,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_platform_token(token: str, *, expected_type: TokenType = "access") -> PlatformPrincipal:
    """Verify a CareOS operator token, or raise.

    Requires the `principal_type` claim explicitly. A tenant token — which does not carry it
    — is therefore refused here, so an agency owner's token cannot reach the platform
    endpoints even though both are signed with the same key.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={
                "require": [
                    "exp",
                    "iat",
                    "iat_us",
                    "sub",
                    "role",
                    "token_type",
                    PRINCIPAL_TYPE_CLAIM,
                ]
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid access token") from exc

    if claims[PRINCIPAL_TYPE_CLAIM] != PLATFORM_PRINCIPAL_TYPE:
        raise AuthenticationError("Not a platform token")
    if claims["token_type"] != expected_type:
        raise AuthenticationError(f"Expected a {expected_type} token")

    try:
        role = PlatformRole(claims["role"])
    except ValueError as exc:
        raise AuthenticationError("Token carries an unrecognized platform role") from exc

    return PlatformPrincipal(
        operator_id=uuid.UUID(claims["sub"]),
        role=role,
        issued_at=datetime.fromtimestamp(claims["iat_us"] / 1_000_000, tz=UTC),
        # Missing reads as not satisfied. See `create_platform_token`.
        mfa_satisfied=claims.get("mfa_satisfied") is True,
    )


def is_platform_token(token: str) -> bool:
    """Whether a bearer token declares itself a platform token.

    Reads the claim **after** verifying the signature, not from the unverified segment, so
    an attacker cannot steer which decoder runs by editing a base64 blob. It costs one extra
    verification on the platform path and none on the tenant path, which is the right way
    round: every caregiver clock-in takes the tenant branch.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            # Nothing required: this answers "which decoder", and the decoder that follows
            # does the real validation, including expiry.
            options={"require": [], "verify_exp": False},
        )
    except jwt.InvalidTokenError:
        # An unverifiable token is not a platform token. It is about to be refused by the
        # tenant decoder with the message that path already produces.
        return False
    return bool(claims.get(PRINCIPAL_TYPE_CLAIM) == PLATFORM_PRINCIPAL_TYPE)
