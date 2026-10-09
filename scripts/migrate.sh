#!/usr/bin/env bash
# Apply database migrations using the published image.
#
# Separate from any hosting platform: migrations need DDL rights and the
# running service deliberately has none, so this runs from your machine
# with the owner credentials rather than from the deployed container.
#
#   ./scripts/migrate.sh <image> <owner-database-url>
#
# Supabase: use the SESSION pooler (port 5432), not the transaction
# pooler (6543). Transaction mode cannot hold a session across a DDL
# run. Connect as `postgres`, which owns the schema.
#
#   ./scripts/migrate.sh youruser/ldap-be:staging \
#     "postgresql+psycopg://postgres.REF:PASSWORD@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"
set -euo pipefail

IMAGE="${1:?usage: migrate.sh <image> <owner-database-url>}"
DB_URL="${2:?usage: migrate.sh <image> <owner-database-url>}"

case "$DB_URL" in
  *:6543/*)
    echo "✗ That is the transaction pooler (port 6543)." >&2
    echo "  Migrations need the session pooler: change 6543 to 5432." >&2
    exit 1 ;;
esac

command -v docker >/dev/null || { echo "✗ docker is not on PATH in this shell" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "✗ the Docker daemon is not running" >&2; exit 1; }

echo "Pulling $IMAGE..."
docker pull -q "$IMAGE" >/dev/null

echo "Applying migrations..."
docker run --rm \
  -e APTUS_ENV=development \
  -e APTUS_DATABASE_URL="$DB_URL" \
  "$IMAGE" sh -c 'cd /srv/api && alembic upgrade head'

cat <<'NEXT'

Done. Now run this once in the Supabase SQL Editor so the runtime role
can read the tables the migration just created:

  GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO aptus_app;
  GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO aptus_app;

NEXT
