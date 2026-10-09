#!/usr/bin/env bash
# Steps 3-6: migrations, Container App, verification.
#
# Fill in the block below, then run. Each step is idempotent and the
# script stops at the first failure with the reason, so a half-finished
# run can be fixed and re-run.
#
#   cp scripts/deploy-azure.sh deploy-azure.local.sh   # keep secrets out of git
#   $EDITOR deploy-azure.local.sh
#   ./deploy-azure.local.sh
#
# Nothing here is written to disk and no value is echoed.

set -euo pipefail

# ─────────────────────────────── fill in ───────────────────────────────

DOCKERHUB_USER=""          # your Docker Hub username
DOCKERHUB_TOKEN=""         # the same access token the GitHub workflow uses
IMAGE_TAG="staging"

SUPABASE_REF=""            # project ref, e.g. abcdefghijklmnop
SUPABASE_REGION="ap-southeast-2"
SUPABASE_DB_PASSWORD=""    # the project's database password (user: postgres)
APTUS_APP_PASSWORD=""      # the password you set on the aptus_app role

ALLOWED_ORIGINS="https://aptus-demo.onrender.com"   # whichever frontend calls this

RESOURCE_GROUP="aptus-staging"
LOCATION="australiaeast"
APP_NAME="aptus-be-staging"
ENV_NAME="aptus-env"

# ───────────────────────────── end fill-in ─────────────────────────────

POOLER="aws-0-${SUPABASE_REGION}.pooler.supabase.com"

# Migrations need session mode (port 5432): transaction mode cannot hold
# a session across the whole DDL run. The app uses transaction mode
# (6543), which is fine and which the engine detects on its own.
MIGRATION_URL="postgresql+psycopg://postgres.${SUPABASE_REF}:${SUPABASE_DB_PASSWORD}@${POOLER}:5432/postgres"
RUNTIME_URL="postgresql+psycopg://aptus_app:${APTUS_APP_PASSWORD}@${POOLER}:6543/postgres"

IMAGE="docker.io/${DOCKERHUB_USER}/ldap-be:${IMAGE_TAG}"

say()  { printf '\n\033[1m── %s\033[0m\n' "$1"; }
ok()   { printf '   \033[32m✓\033[0m %s\n' "$1"; }
die()  { printf '   \033[31m✗ %s\033[0m\n' "$1"; exit 1; }

for v in DOCKERHUB_USER DOCKERHUB_TOKEN SUPABASE_REF SUPABASE_DB_PASSWORD APTUS_APP_PASSWORD; do
  [ -n "${!v}" ] || die "$v is empty — fill in the block at the top of this script"
done
# Both must exist in THIS shell. On Windows the usual trap is the Azure
# CLI installed in PowerShell while this script runs under WSL or Git
# Bash, where it is not on PATH.
command -v az >/dev/null || die "the Azure CLI is not on PATH in this shell.
     WSL/Ubuntu: curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
     macOS:      brew install azure-cli"
command -v docker >/dev/null || die "docker is not on PATH in this shell"

# Checked here rather than left to fail partway through. In WSL, SSH, a
# devcontainer or Codespaces the CLI cannot open a browser, so plain
# 'az login' hangs; device code works everywhere.
az account show >/dev/null 2>&1 || die "not signed in to Azure. Run:
     az login --use-device-code
   then, if you have more than one subscription:
     az account set --subscription \"<name or id>\""

docker info >/dev/null 2>&1 || die "the Docker daemon is not running"

# ── 3. Migrations ──────────────────────────────────────────────────────
say "3. Applying migrations over the session pooler"
docker pull -q "$IMAGE" >/dev/null || die "cannot pull $IMAGE — is the tag published?"
docker run --rm \
  -e APTUS_ENV=development \
  -e APTUS_DATABASE_URL="$MIGRATION_URL" \
  "$IMAGE" sh -c 'cd /srv/api && alembic upgrade head' \
  || die "migrations failed — check the connection string and that the project is not paused"
ok "schema at head"

printf '   %s\n' "Now run this once in the Supabase SQL Editor, then press Enter:"
cat <<'GRANTS'

     GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO aptus_app;
     GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO aptus_app;

GRANTS
read -r -p "   Press Enter once the grants have run... " _

# ── 4. Container App ───────────────────────────────────────────────────
say "4. Creating or updating the Container App"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --only-show-errors >/dev/null
az containerapp env show --name "$ENV_NAME" --resource-group "$RESOURCE_GROUP" --only-show-errors >/dev/null 2>&1 \
  || az containerapp env create --name "$ENV_NAME" --resource-group "$RESOURCE_GROUP" \
       --location "$LOCATION" --only-show-errors >/dev/null
ok "resource group and environment ready"

SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"

if az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --only-show-errors >/dev/null 2>&1; then
  # Updating: leave the existing secret-key alone so sessions issued
  # before this deploy keep working.
  az containerapp secret set --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
    --secrets db-url="$RUNTIME_URL" --only-show-errors >/dev/null
  az containerapp update --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
    --image "$IMAGE" --only-show-errors >/dev/null
  ok "existing app updated"
else
  az containerapp create \
    --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --environment "$ENV_NAME" \
    --image "$IMAGE" \
    --registry-server docker.io \
    --registry-username "$DOCKERHUB_USER" --registry-password "$DOCKERHUB_TOKEN" \
    --target-port 8080 --ingress external \
    --cpu 0.25 --memory 0.5Gi --min-replicas 0 --max-replicas 1 \
    --secrets secret-key="$SECRET_KEY" db-url="$RUNTIME_URL" \
    --env-vars \
        APTUS_ENV=production \
        APTUS_SECRET_KEY=secretref:secret-key \
        APTUS_DATABASE_URL=secretref:db-url \
        APTUS_ALLOWED_ORIGINS="$ALLOWED_ORIGINS" \
        APTUS_REQUIRE_EMAIL_VERIFICATION=false \
    --only-show-errors >/dev/null
  ok "app created"
fi

URL="https://$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
      --query properties.configuration.ingress.fqdn -o tsv --only-show-errors)"
ok "$URL"

# ── 5. Verify ──────────────────────────────────────────────────────────
say "5. Verifying"
# min-replicas is 0, so the first request pays a cold start.
for _ in $(seq 1 40); do curl -sf "$URL/health" >/dev/null 2>&1 && break; sleep 3; done
curl -sf "$URL/health" >/dev/null || die "the app is not answering — az containerapp logs show --name $APP_NAME --resource-group $RESOURCE_GROUP"
ok "health"

curl -s "$URL/version" | python3 -c "import json,sys;d=json.load(sys.stdin);print('   engine config',d['engine_config_version'],'digest',d['engine_config_digest'][:12])"

# The one that matters. Policies that are not enforced look exactly like
# policies that are, until someone reads another tenant's data.
curl -s "$URL/rls" | python3 -c "
import json,sys
d=json.load(sys.stdin)
if not d['enforced']:
    sys.exit('   ✗ row-level security NOT enforced: ' + '; '.join(d['problems']))
print(f\"   ✓ row-level security enforced as {d['role']} across {len(d['tables'])} tables\")
" || die "tenant isolation is not enforced — do not demo this"

say "6. Next"
cat <<NEXT
   Seed the demonstration references (session pooler, as postgres):

     python3 scripts/seed-demo-references.py \\
       "postgresql+psycopg://postgres.${SUPABASE_REF}:<DB_PASSWORD>@${POOLER}:5432/postgres"

   Then the full walkthrough — expect 36 passed:

     ./scripts/demo.sh $URL

   Before a demo: scale-to-zero costs a few seconds on the first
   request, so warm it with a curl. Free Supabase projects pause after
   about a week idle — open the project the day before.
NEXT
