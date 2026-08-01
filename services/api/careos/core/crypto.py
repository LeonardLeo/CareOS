"""Field-level encryption for the most sensitive PII.

`08_Security_Architecture.md` Section 3 requires field-level encryption for SSN/tax ID,
date of birth, and precise home address, *on top of* database-level encryption at rest, so
that compromise of the database alone does not expose these fields in plaintext. That only
holds if the key lives outside the database — in deployed environments it comes from the
secrets manager, never from a table or a committed file.

AES-256-GCM, so each ciphertext is authenticated: tampering is detected on decrypt rather
than silently yielding wrong plaintext. The 96-bit nonce is random per encryption and
prefixed to the ciphertext, so encrypting the same address twice produces different bytes
and an attacker cannot identify shared addresses by comparing rows.
"""

from __future__ import annotations

import base64
import os
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_BYTES = 12
_KEY_BYTES = 32

#: Development-only key, used when CAREOS_FIELD_ENCRYPTION_KEY is unset. `get_field_key`
#: refuses to fall back to it outside local/test environments.
_DEV_KEY = b"\x00" * _KEY_BYTES


class FieldDecryptionError(Exception):
    """Ciphertext failed authentication — wrong key, or the data was tampered with."""


@lru_cache
def get_field_key() -> bytes:
    from careos.config import get_settings

    settings = get_settings()
    raw = os.environ.get("CAREOS_FIELD_ENCRYPTION_KEY")
    if not raw:
        if settings.environment in {"local", "test"}:
            return _DEV_KEY
        raise RuntimeError(
            "CAREOS_FIELD_ENCRYPTION_KEY must be set outside local/test environments "
            "(08_Security_Architecture.md Section 3)"
        )
    key = base64.b64decode(raw)
    if len(key) != _KEY_BYTES:
        raise RuntimeError(
            f"CAREOS_FIELD_ENCRYPTION_KEY must decode to {_KEY_BYTES} bytes, got {len(key)}"
        )
    return key


def encrypt_field(plaintext: str | None) -> bytes | None:
    """Encrypt a sensitive field. None passes through so optional columns stay nullable."""
    if plaintext is None:
        return None
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(get_field_key()).encrypt(nonce, plaintext.encode(), None)
    return nonce + ciphertext


def decrypt_field(blob: bytes | None) -> str | None:
    if blob is None:
        return None
    if len(blob) <= _NONCE_BYTES:
        raise FieldDecryptionError("Ciphertext is too short to contain a nonce")
    nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    try:
        return AESGCM(get_field_key()).decrypt(nonce, ciphertext, None).decode()
    except InvalidTag as exc:
        raise FieldDecryptionError(
            "Field failed authenticated decryption — wrong key or tampered ciphertext"
        ) from exc


def generate_key_b64() -> str:
    """Generate a new key, for provisioning into the secrets manager."""
    return base64.b64encode(os.urandom(_KEY_BYTES)).decode()
