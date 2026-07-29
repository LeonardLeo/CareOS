"""Field-level encryption and schema-guard tests."""

from __future__ import annotations

import base64
import os

import pytest
from sqlalchemy import text

from careos.core.crypto import (
    FieldDecryptionError,
    decrypt_field,
    encrypt_field,
    generate_key_b64,
)
from careos.db.models import (
    GLOBAL_TABLES,
    RLS_TABLES,
    TENANT_ROOT_TABLE,
    TENANT_TABLES,
    Base,
    assert_every_table_is_classified,
)
from careos.db.rls import _quote
from careos.db.session import tenant_session

# --- Field-level encryption ---------------------------------------------------------------


def test_roundtrip() -> None:
    assert decrypt_field(encrypt_field("123-45-6789")) == "123-45-6789"


def test_none_passes_through() -> None:
    assert encrypt_field(None) is None
    assert decrypt_field(None) is None


def test_ciphertext_is_not_the_plaintext() -> None:
    blob = encrypt_field("1 Test Street, New York NY")
    assert b"Test Street" not in blob


def test_same_plaintext_encrypts_differently_each_time() -> None:
    """A random per-encryption nonce stops an attacker spotting shared addresses by
    comparing ciphertext across rows."""
    a = encrypt_field("1 Test Street")
    b = encrypt_field("1 Test Street")
    assert a != b
    assert decrypt_field(a) == decrypt_field(b) == "1 Test Street"


def test_tampering_is_detected() -> None:
    """AES-GCM authenticates, so a modified ciphertext fails rather than decrypting wrongly."""
    blob = bytearray(encrypt_field("sensitive"))
    blob[-1] ^= 0xFF
    with pytest.raises(FieldDecryptionError):
        decrypt_field(bytes(blob))


def test_truncated_ciphertext_is_rejected() -> None:
    with pytest.raises(FieldDecryptionError):
        decrypt_field(b"short")


def test_generated_key_is_the_right_size() -> None:
    assert len(base64.b64decode(generate_key_b64())) == 32


async def test_pii_is_ciphertext_at_rest(client, tenant_a) -> None:
    """Confirms the column really holds ciphertext, not just that the helper works.

    Written through the API so the production encryption path is the one exercised, then
    read back with raw SQL so the assertion is about the stored bytes.
    """
    response = await client.post(
        "/v1/clients",
        headers=tenant_a.headers(),
        json={
            "legal_name": "Encrypted Client",
            "dob": "1940-03-02",
            "address": "1 Secret Lane, New York NY",
            "service_state": "NY",
            "primary_payer_type": "private_pay",
        },
    )
    assert response.status_code == 201
    client_id = response.json()["id"]

    async with tenant_session(tenant_a.agency_id) as session:
        row = (
            await session.execute(
                text("SELECT dob_encrypted, address_encrypted FROM client WHERE id = :cid"),
                {"cid": client_id},
            )
        ).one()

    dob_blob, address_blob = row
    assert dob_blob is not None and address_blob is not None
    assert b"1940" not in dob_blob
    assert b"Secret Lane" not in address_blob
    # And it is genuinely recoverable, not merely mangled.
    assert decrypt_field(dob_blob) == "1940-03-02"
    assert decrypt_field(address_blob) == "1 Secret Lane, New York NY"


# --- Schema guards --------------------------------------------------------------------------


def test_every_table_is_classified() -> None:
    assert_every_table_is_classified()


def test_tenant_tables_all_carry_the_tenant_key() -> None:
    for table_name in TENANT_TABLES:
        assert "agency_id" in Base.metadata.tables[table_name].columns


def test_rls_tables_cover_everything_that_is_not_global() -> None:
    non_global = {name for name in Base.metadata.tables if name not in GLOBAL_TABLES}
    assert set(RLS_TABLES) == non_global


def test_tenant_root_is_not_in_tenant_tables() -> None:
    """The tenant root keys on `id`, so it must not be treated as an `agency_id` table."""
    assert TENANT_ROOT_TABLE not in TENANT_TABLES
    assert TENANT_ROOT_TABLE in RLS_TABLES


def test_phase2_and_phase3_tables_exist_from_the_first_release() -> None:
    """`03_Technical_Architecture.md` Section 1: design for Phase 3 from Phase 1.

    These tables carry no data yet. They exist so that visits recorded today can be traced
    onto a claim line in Phase 3 without a backfill.
    """
    for table in (
        "visit_note",
        "ambient_session_metadata",
        "payer_contract",
        "authorization",
        "claim",
        "claim_line",
        "remittance",
    ):
        assert table in Base.metadata.tables, f"{table} is missing from the schema"


def test_claim_line_traces_back_to_a_visit() -> None:
    """The lineage that makes Phase 3 denial root-causing tractable."""
    columns = Base.metadata.tables["claim_line"].columns
    assert "scheduled_visit_id" in columns
    assert "authorization_id" in columns


def test_visit_carries_billing_fields_from_phase_one() -> None:
    columns = Base.metadata.tables["scheduled_visit"].columns
    for column in ("service_type_code", "service_state", "payer_type", "authorization_id"):
        assert column in columns


def test_quote_rejects_a_suspicious_identifier() -> None:
    """The RLS helper interpolates table names into DDL, so it validates them."""
    assert _quote("authorization") == '"authorization"'
    with pytest.raises(ValueError):
        _quote('client"; DROP TABLE client; --')


async def test_reference_tables_are_read_only_to_the_app_role(database: None) -> None:
    """Reference data is migration/seed-owned; the application may read but not write it."""
    from sqlalchemy.exc import ProgrammingError

    async with tenant_session(None) as session:
        with pytest.raises(ProgrammingError):
            await session.execute(
                text(
                    "INSERT INTO evv_aggregator_ref "
                    "(state_code, adapter_key, evv_model, aggregator_name, created_at, "
                    " updated_at) "
                    "VALUES ('ZZ', 'loopback', 'state_mandated_vendor', 'x', now(), now())"
                )
            )


async def test_app_role_can_read_reference_tables(database: None, reference_data: None) -> None:
    async with tenant_session(None) as session:
        count = (
            await session.execute(text("SELECT count(*) FROM evv_aggregator_ref"))
        ).scalar_one()
    assert count >= 1


def test_field_key_is_required_outside_local_and_test(monkeypatch) -> None:
    """A deployed environment must not silently fall back to the development key."""
    import careos.config as config_module
    from careos.config import Settings
    from careos.core import crypto

    monkeypatch.delenv("CAREOS_FIELD_ENCRYPTION_KEY", raising=False)
    # `crypto.get_field_key` imports get_settings from careos.config at call time, so
    # patching it there is what takes effect.
    monkeypatch.setattr(config_module, "get_settings", lambda: Settings(environment="staging"))

    crypto.get_field_key.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="CAREOS_FIELD_ENCRYPTION_KEY"):
            crypto.get_field_key()
    finally:
        crypto.get_field_key.cache_clear()


def test_field_key_must_be_32_bytes(monkeypatch) -> None:
    from careos.core import crypto

    crypto.get_field_key.cache_clear()
    monkeypatch.setenv("CAREOS_FIELD_ENCRYPTION_KEY", base64.b64encode(os.urandom(16)).decode())
    with pytest.raises(RuntimeError, match="32 bytes"):
        crypto.get_field_key()
    crypto.get_field_key.cache_clear()
    monkeypatch.delenv("CAREOS_FIELD_ENCRYPTION_KEY", raising=False)
