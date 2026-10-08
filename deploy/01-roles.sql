-- Database roles for an Aptus deployment.
--
-- Run once per database, as a superuser, BEFORE the first migration.
-- Roles are cluster-level objects, so they are not part of the Alembic
-- chain: a migration that created roles would need superuser rights at
-- every deploy, which is exactly what we are trying to avoid.
--
-- Two roles, deliberately:
--
--   aptus_owner  owns the schema and runs migrations. Needs DDL rights.
--   aptus_app    the runtime connection. Owns nothing, is not a
--                superuser, and does not have BYPASSRLS -- which is the
--                whole point. Any of those three would silently disable
--                every row-level-security policy.
--
-- The application refuses to start in production if it detects that its
-- own role bypasses RLS. See src/aptus_api/rls.py.

\set ON_ERROR_STOP on

-- Replace these before running.
\set owner_password 'CHANGE_ME_OWNER'
\set app_password   'CHANGE_ME_APP'

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aptus_owner') THEN
    CREATE ROLE aptus_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aptus_app') THEN
    CREATE ROLE aptus_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END
$$;

ALTER ROLE aptus_owner PASSWORD :'owner_password';
ALTER ROLE aptus_app   PASSWORD :'app_password';

-- Guard against a role that was created earlier with wider rights.
ALTER ROLE aptus_owner NOSUPERUSER NOBYPASSRLS;
ALTER ROLE aptus_app   NOSUPERUSER NOBYPASSRLS;

GRANT CONNECT ON DATABASE :"DBNAME" TO aptus_owner, aptus_app;
ALTER SCHEMA public OWNER TO aptus_owner;
GRANT USAGE ON SCHEMA public TO aptus_app;

-- The app gets data rights only: no DDL, so it can never drop a policy.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO aptus_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO aptus_app;

-- And the same for tables a future migration creates.
ALTER DEFAULT PRIVILEGES FOR ROLE aptus_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO aptus_app;
ALTER DEFAULT PRIVILEGES FOR ROLE aptus_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO aptus_app;
