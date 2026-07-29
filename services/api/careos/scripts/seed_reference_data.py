"""Seed the global reference tables.

Run after migrations, on every environment. Reference data is migration/seed-owned — the
application roles hold SELECT only — so this connects with the migration credential.

**The rows below are starting scaffolding, not verified fact.**
`06_Compliance_and_Regulatory_Requirements.md` Section 1 is explicit that states
periodically change EVV vendors, and Section 4 that Medicaid service codes and rates vary by
state and by waiver program. Confirm the current assignment for any state before operating
there, and re-verify annually per that document's Section 9 cadence. `sandbox_validated` is
left false for every real aggregator on purpose: the registry refuses to transmit production
data through an adapter that has not been validated against the vendor's sandbox.

Usage:
    python -m careos.scripts.seed_reference_data
"""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from careos.config import get_settings

logger = structlog.get_logger(__name__)

#: (state, adapter_key, evv_model, aggregator_name, note)
EVV_AGGREGATORS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "NY",
        "hhaexchange",
        "state_mandated_vendor",
        "HHAeXchange",
        "UNVERIFIED - confirm current NY assignment before operating in this state",
    ),
    (
        "FL",
        "tellus",
        "state_mandated_vendor",
        "Tellus",
        "UNVERIFIED - confirm current FL assignment before operating in this state",
    ),
    (
        "TX",
        "hhaexchange",
        "state_mandated_vendor",
        "HHAeXchange",
        "UNVERIFIED - confirm current TX assignment before operating in this state",
    ),
    (
        "CA",
        "sandata",
        "open_vendor_to_aggregator",
        "Sandata",
        "UNVERIFIED - confirm current CA assignment before operating in this state",
    ),
    (
        "PA",
        "sandata",
        "state_mandated_vendor",
        "Sandata",
        "UNVERIFIED - confirm current PA assignment before operating in this state",
    ),
)

#: Credential types relevant to home-based care. `blocks_scheduling_on_expiry` reflects
#: whether an expired credential should stop assignment outright or merely warn.
CREDENTIAL_TYPES: tuple[tuple[str, str, bool], ...] = (
    ("HHA", "Home Health Aide", True),
    ("CNA", "Certified Nursing Assistant", True),
    ("PCA", "Personal Care Aide", True),
    ("RN", "Registered Nurse License", True),
    ("LPN", "Licensed Practical Nurse License", True),
    ("CPR", "CPR Certification", True),
    ("TB_TEST", "Tuberculosis Screening", True),
    ("DRIVERS_LICENSE", "Driver's License", False),
    ("AUTO_INSURANCE", "Auto Insurance", False),
)

#: Service codes. Deliberately sparse — a real deployment populates these per state and
#: payer contract with a certified billing consultant, per `06_Compliance...` Section 9.
SERVICE_CODES: tuple[tuple[str, str, str, str, int], ...] = (
    ("T1019", "NY", "medicaid_waiver", "Personal care services, per 15 minutes", 15),
    ("T1019", "FL", "medicaid_waiver", "Personal care services, per 15 minutes", 15),
    ("T1019", "TX", "medicaid_waiver", "Personal care services, per 15 minutes", 15),
    ("T1019", "CA", "medicaid_waiver", "Personal care services, per 15 minutes", 15),
    ("T1019", "PA", "medicaid_waiver", "Personal care services, per 15 minutes", 15),
    ("S5125", "NY", "medicaid_waiver", "Attendant care services, per 15 minutes", 15),
    ("PRIVATE_HR", "NY", "private_pay", "Private pay hourly care", 60),
    ("PRIVATE_HR", "FL", "private_pay", "Private pay hourly care", 60),
)


async def seed() -> None:
    engine = create_async_engine(get_settings().migration_database_url)
    try:
        async with engine.begin() as conn:
            for state, adapter, model, name, note in EVV_AGGREGATORS:
                await conn.execute(
                    text(
                        """
                        INSERT INTO evv_aggregator_ref
                            (state_code, adapter_key, evv_model, aggregator_name,
                             connection_config, sandbox_validated, notes,
                             created_at, updated_at)
                        VALUES (:state, :adapter, CAST(:model AS evv_model), :name,
                                '{}'::jsonb, false, :note, now(), now())
                        ON CONFLICT (state_code) DO NOTHING
                        """
                    ),
                    {
                        "state": state,
                        "adapter": adapter,
                        "model": model,
                        "name": name,
                        "note": note,
                    },
                )

            for code, display, blocks in CREDENTIAL_TYPES:
                await conn.execute(
                    text(
                        """
                        INSERT INTO credential_type_ref
                            (code, display_name, state_requirements,
                             blocks_scheduling_on_expiry, created_at, updated_at)
                        VALUES (:code, :display, '{}'::jsonb, :blocks, now(), now())
                        ON CONFLICT (code) DO NOTHING
                        """
                    ),
                    {"code": code, "display": display, "blocks": blocks},
                )

            for code, state, payer, display, minutes in SERVICE_CODES:
                await conn.execute(
                    text(
                        """
                        INSERT INTO payer_service_code_ref
                            (code, state_code, payer_type, display_name, unit_minutes,
                             billing_rules, requires_evv, created_at, updated_at)
                        VALUES (:code, :state, :payer, :display, :minutes, '{}'::jsonb,
                                :requires_evv, now(), now())
                        ON CONFLICT (code, state_code, payer_type) DO NOTHING
                        """
                    ),
                    {
                        "code": code,
                        "state": state,
                        "payer": payer,
                        "display": display,
                        "minutes": minutes,
                        # EVV is mandated for Medicaid-funded services; private pay is not.
                        "requires_evv": payer != "private_pay",
                    },
                )
    finally:
        await engine.dispose()

    logger.info(
        "reference_data.seeded",
        aggregators=len(EVV_AGGREGATORS),
        credential_types=len(CREDENTIAL_TYPES),
        service_codes=len(SERVICE_CODES),
    )


if __name__ == "__main__":
    asyncio.run(seed())
