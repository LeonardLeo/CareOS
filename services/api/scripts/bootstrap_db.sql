-- Cluster/database bootstrap for local development and CI.
--
-- Roles are cluster-level objects, so they are provisioned here rather than in a
-- migration. In staging and production the equivalent roles are created by Terraform with
-- credentials issued from the secrets manager (`08_Security_Architecture.md` Section 5);
-- this script exists so a developer or CI runner can reach the same shape with one command.
--
-- Run as a superuser:  psql -v ON_ERROR_STOP=1 -f scripts/bootstrap_db.sql
--
-- The four roles are the application-layer half of the isolation model in
-- `08_Security_Architecture.md` Section 2:
--
--   careos_app            -- every tenant request handler. No BYPASSRLS, so Row-Level
--                            Security binds it.
--   careos_auth           -- BYPASSRLS. Login lookups and agency provisioning only; these
--                            happen before a tenant is known, so they cannot be
--                            tenant-scoped.
--   careos_platform       -- the CareOS operator console. No BYPASSRLS either. Its
--                            cross-tenant reach is one SELECT grant on one aggregate view
--                            of counts, plus a column-scoped grant on `agency` so an
--                            agency can be suspended. It holds nothing on any table
--                            carrying PHI.
--   careos_platform_views -- NOLOGIN. Owns that view, and exists only so the view can read
--                            across tenants without careos_platform being granted anything
--                            on the base tables. Nothing can connect as it.
--
-- Re-running this is safe and is the correct way to add the two platform roles to a
-- database created before they existed. Migration 0013 refuses to run without them.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'careos_app') THEN
        CREATE ROLE careos_app LOGIN PASSWORD 'careos_app';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'careos_auth') THEN
        CREATE ROLE careos_auth LOGIN PASSWORD 'careos_auth' BYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'careos_platform') THEN
        CREATE ROLE careos_platform LOGIN PASSWORD 'careos_platform';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'careos_platform_views') THEN
        -- NOLOGIN is the whole point: this role owns the aggregate view and is not a way in.
        CREATE ROLE careos_platform_views NOLOGIN;
    END IF;
END
$$;

-- Explicitly assert the security-relevant attributes rather than assuming them. If a
-- previous run or an operator granted BYPASSRLS to one of these, every isolation guarantee
-- below it silently evaporates, so fail loudly instead.
--
-- careos_platform is included for the same reason careos_app is, and the temptation is
-- stronger: it is the role that legitimately needs to see something about every tenant, so
-- "just give it BYPASSRLS" is the shortcut somebody will reach for. The aggregate view is
-- the answer to that, and this assertion is what stops the shortcut being taken quietly.
DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['careos_app', 'careos_platform', 'careos_platform_views'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r AND rolbypassrls) THEN
            RAISE EXCEPTION
                '% must not hold BYPASSRLS - it would defeat tenant isolation', r;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r AND rolsuper) THEN
            RAISE EXCEPTION '% must not be a superuser - superusers bypass RLS', r;
        END IF;
    END LOOP;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'careos_platform_views' AND rolcanlogin)
    THEN
        RAISE EXCEPTION
            'careos_platform_views must not be able to log in - it owns the cross-tenant '
            'view and is not an account';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO careos_app;
GRANT USAGE ON SCHEMA public TO careos_auth;
GRANT USAGE ON SCHEMA public TO careos_platform;
GRANT USAGE ON SCHEMA public TO careos_platform_views;
