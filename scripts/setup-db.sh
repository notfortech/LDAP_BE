#!/usr/bin/env bash
# Prepare a database for development or testing:
#   1. create the two roles,
#   2. run migrations as the owner,
#   3. verify the runtime role is actually constrained by RLS.
#
# Usage:  ./scripts/setup-db.sh [host] [port] [database]
set -euo pipefail

HOST="${1:-localhost}"
PORT="${2:-5432}"
DB="${3:-aptus}"
SUPER="${PGSUPERUSER:-postgres}"
OWNER_PW="${APTUS_OWNER_PASSWORD:-ownerpw}"
APP_PW="${APTUS_APP_PASSWORD:-apppw}"

psql -h "$HOST" -p "$PORT" -U "$SUPER" -d "$DB" -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='aptus_owner') THEN
    CREATE ROLE aptus_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='aptus_app') THEN
    CREATE ROLE aptus_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END
\$\$;
ALTER ROLE aptus_owner PASSWORD '$OWNER_PW' NOSUPERUSER NOBYPASSRLS;
ALTER ROLE aptus_app   PASSWORD '$APP_PW'   NOSUPERUSER NOBYPASSRLS;
GRANT CONNECT ON DATABASE "$DB" TO aptus_owner, aptus_app;
ALTER SCHEMA public OWNER TO aptus_owner;
GRANT USAGE ON SCHEMA public TO aptus_app;
SQL

echo "roles ready; running migrations as aptus_owner"
(
  cd "$(dirname "$0")/../api"
  APTUS_ENV=development \
  APTUS_DATABASE_URL="postgresql+psycopg://aptus_owner:${OWNER_PW}@${HOST}:${PORT}/${DB}" \
    python -m alembic upgrade head
)

psql -h "$HOST" -p "$PORT" -U "$SUPER" -d "$DB" -v ON_ERROR_STOP=1 <<SQL
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO aptus_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO aptus_app;
ALTER DEFAULT PRIVILEGES FOR ROLE aptus_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO aptus_app;
ALTER DEFAULT PRIVILEGES FOR ROLE aptus_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO aptus_app;
SQL

echo
echo "Verifying the runtime role is constrained by row-level security..."
psql -h "$HOST" -p "$PORT" -U "$SUPER" -d "$DB" -tAc \
  "SELECT 'aptus_app superuser=' || rolsuper || ' bypassrls=' || rolbypassrls
     FROM pg_roles WHERE rolname='aptus_app'"
psql -h "$HOST" -p "$PORT" -U "$SUPER" -d "$DB" -tAc \
  "SELECT relname || ': rls=' || relrowsecurity || ' forced=' || relforcerowsecurity
     FROM pg_class WHERE relrowsecurity ORDER BY relname"

cat <<MSG

Done. To run the row-level-security tests:

  export APTUS_TEST_APP_DATABASE_URL="postgresql+psycopg://aptus_app:${APP_PW}@${HOST}:${PORT}/${DB}"
  export APTUS_TEST_ADMIN_DATABASE_URL="postgresql+psycopg://aptus_owner:${OWNER_PW}@${HOST}:${PORT}/${DB}"
  cd api && pytest tests/test_rls.py -v

To run the API against this database:

  export APTUS_DATABASE_URL="postgresql+psycopg://aptus_app:${APP_PW}@${HOST}:${PORT}/${DB}"
  uvicorn aptus_api.main:create_app --factory --reload
  curl localhost:8000/rls
MSG
