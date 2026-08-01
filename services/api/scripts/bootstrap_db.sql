-- Cluster/database bootstrap for local development and CI.
--
-- Roles are cluster-level objects, so they are provisioned here rather than in a
-- migration. In staging and production the equivalent roles are created by Terraform with
-- credentials issued from the secrets manager (`08_Security_Architecture.md` Section 5);
-- this script exists so a developer or CI runner can reach the same shape with one command.
--
-- Run as a superuser:  psql -v ON_ERROR_STOP=1 -f scripts/bootstrap_db.sql
--
-- The two roles are the application-layer half of the isolation model in
-- `08_Security_Architecture.md` Section 2:
--
--   careos_app   -- every request handler. No BYPASSRLS, so Row-Level Security binds it.
--   careos_auth  -- BYPASSRLS. Login lookups and agency provisioning only; these happen
--                   before a tenant is known, so they cannot be tenant-scoped.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'careos_app') THEN
        CREATE ROLE careos_app LOGIN PASSWORD 'careos_app';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'careos_auth') THEN
        CREATE ROLE careos_auth LOGIN PASSWORD 'careos_auth' BYPASSRLS;
    END IF;
END
$$;

-- Explicitly assert the security-relevant attribute rather than assuming it. If a previous
-- run or an operator granted BYPASSRLS to the application role, every isolation guarantee
-- below it silently evaporates, so fail loudly instead.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'careos_app' AND rolbypassrls) THEN
        RAISE EXCEPTION
            'careos_app must not hold BYPASSRLS - it would defeat tenant isolation';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'careos_app' AND rolsuper) THEN
        RAISE EXCEPTION 'careos_app must not be a superuser - superusers bypass RLS';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO careos_app;
GRANT USAGE ON SCHEMA public TO careos_auth;
