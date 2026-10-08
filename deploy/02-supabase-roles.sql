-- Application role for a Supabase-hosted database.
--
-- Run once in the Supabase SQL Editor, which connects as `postgres`.
--
-- Why this differs from 01-roles.sql
-- ----------------------------------
-- On hosted Supabase you cannot run `ALTER ROLE ... NOSUPERUSER`
-- (SQLSTATE 42501 -- `postgres` is not a true superuser there), and you
-- cannot take ownership of the `public` schema. So 01-roles.sql does not
-- apply. This script sets every attribute at CREATE ROLE instead, which
-- is permitted, and leaves ownership alone.
--
-- What matters for tenant isolation
-- ---------------------------------
-- Supabase's `postgres` role carries BYPASSRLS, so it ignores every
-- policy. That is fine for migrations, which need DDL anyway -- it is
-- the equivalent of `aptus_owner` in a self-managed deployment.
--
-- What must never carry BYPASSRLS is the role the application connects
-- as at runtime. That is the role created below. It owns nothing, has
-- no DDL rights, and cannot drop a policy.
--
-- Replace the password before running, and use a generated one:
--   python3 -c 'import secrets; print(secrets.token_urlsafe(32))'

CREATE ROLE aptus_app
  LOGIN
  PASSWORD 'REPLACE_ME'
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  NOINHERIT
  NOBYPASSRLS;

GRANT USAGE ON SCHEMA public TO aptus_app;

-- Data rights only. No CREATE on the schema, so the runtime connection
-- cannot alter the schema or disable a policy.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO aptus_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO aptus_app;

-- And the same for whatever a later migration creates. `postgres` runs
-- the migrations, so the default privileges are declared for it.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO aptus_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO aptus_app;

-- Verify. Both columns must read false. If either is true, the
-- application would silently bypass every policy -- and it will refuse
-- to start in production rather than do so.
SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole
FROM pg_roles
WHERE rolname = 'aptus_app';
