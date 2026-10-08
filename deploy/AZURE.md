# Deploying to Azure Container Apps

Docker Hub for the image, Azure Database for PostgreSQL Flexible Server
for the data, Azure Container Apps for the runtime. Staging only — see
the note on residency at the end before any real learner data.

Everything in the repository is ready. What follows is the part only you
can do: creating accounts, resources and secrets.

---

## 1. GitHub — add the Docker Hub secrets

The workflow is already committed at
`.github/workflows/build-and-push.yml`. It needs two secrets.

1. Docker Hub → **Account Settings → Personal access tokens → Generate
   new token**. Scope **Read & Write**. Copy it now; it is shown once.
2. GitHub → your repository → **Settings → Secrets and variables →
   Actions → New repository secret**:

   | Name | Value |
   |---|---|
   | `DOCKERHUB_USERNAME` | your Docker Hub username |
   | `DOCKERHUB_TOKEN` | the access token |

Use a token, never your password: a token is scoped and revocable on its
own.

## 2. GitHub — run the workflow

**Actions → build-and-push → Run workflow**, tag `staging`.

It builds the image, stands up PostgreSQL, applies migrations using the
image's own Alembic, runs the image, and checks `/health`, `/version`
and `/rls`. **Only then** does it push. A tag in a registry is a tag
someone can deploy, so an unverified one never gets there.

Roughly four minutes the first time, under two after that.

## 3. Docker Hub — confirm the image

`hub.docker.com` → Repositories → `YOUR_USERNAME/ldap-be`. Two tags:
`staging`, and the first twelve characters of the commit. The second is
how you trace a running container back to its source.

**Make the repository private** (Settings → Make private) unless you
intend it public. Azure is configured for a private pull below either
way.

## 4. Azure — the database, first

The app will not start without it.

```bash
az login
az group create --name aptus-staging --location australiaeast

az postgres flexible-server create \
  --resource-group aptus-staging \
  --name aptus-staging-db \
  --location australiaeast \
  --tier Burstable --sku-name Standard_B1ms \
  --storage-size 32 \
  --version 16 \
  --admin-user pgadmin \
  --admin-password '<a-strong-password>' \
  --public-access 0.0.0.0

az postgres flexible-server db create \
  --resource-group aptus-staging \
  --server-name aptus-staging-db \
  --database-name aptus
```

`--public-access 0.0.0.0` means "allow Azure services", not "allow the
internet". Container Apps needs it. Add your own IP too so you can run
the migration step:

```bash
az postgres flexible-server firewall-rule create \
  --resource-group aptus-staging --name aptus-staging-db \
  --rule-name my-laptop \
  --start-ip-address <your-ip> --end-ip-address <your-ip>
```

### Create the two roles

This is what makes tenant isolation real. The app connects as a role
that **cannot** bypass row-level security; a superuser or `BYPASSRLS`
connection ignores every policy silently. The app refuses to start if it
detects that, but create the roles properly regardless.

```bash
psql "host=aptus-staging-db.postgres.database.azure.com port=5432 \
      dbname=aptus user=pgadmin sslmode=require"
```

```sql
CREATE ROLE aptus_owner LOGIN PASSWORD '<owner-password>'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE aptus_app   LOGIN PASSWORD '<app-password>'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

GRANT CONNECT ON DATABASE aptus TO aptus_owner, aptus_app;
ALTER SCHEMA public OWNER TO aptus_owner;
GRANT USAGE ON SCHEMA public TO aptus_app;

ALTER DEFAULT PRIVILEGES FOR ROLE aptus_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO aptus_app;
ALTER DEFAULT PRIVILEGES FOR ROLE aptus_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO aptus_app;
```

On Azure Flexible Server `pgadmin` is not a true superuser, so it cannot
create a role with powers it lacks. That is in your favour here.

### Run the migrations

Container Apps has no release-command hook, so migrations are a separate
step. Run them from your machine with the image you just published —
same Alembic, same migrations, nothing to drift:

```bash
docker run --rm \
  -e APTUS_ENV=development \
  -e APTUS_DATABASE_URL="postgresql+psycopg://aptus_owner:<owner-password>@aptus-staging-db.postgres.database.azure.com:5432/aptus?sslmode=require" \
  YOUR_USERNAME/ldap-be:staging \
  sh -c 'cd /srv/api && alembic upgrade head'
```

Then grant the app role rights on the tables that migration just created
(the default privileges above cover every later migration):

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO aptus_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO aptus_app;
```

Keep the owner password off the Container App entirely. The runtime has
no DDL rights by design, so a compromised runtime connection cannot drop
a policy.

## 5. Azure — the Container App

```bash
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights

az containerapp env create \
  --name aptus-env --resource-group aptus-staging --location australiaeast

az containerapp create \
  --name aptus-backend \
  --resource-group aptus-staging \
  --environment aptus-env \
  --image docker.io/YOUR_USERNAME/ldap-be:staging \
  --registry-server docker.io \
  --registry-username YOUR_USERNAME \
  --registry-password '<docker-hub-token>' \
  --target-port 8080 \
  --ingress external \
  --min-replicas 1 --max-replicas 2 \
  --cpu 0.5 --memory 1.0Gi \
  --secrets \
      secret-key='<generate-a-48-char-random-string>' \
      db-url='postgresql+psycopg://aptus_app:<app-password>@aptus-staging-db.postgres.database.azure.com:5432/aptus?sslmode=require' \
  --env-vars \
      APTUS_ENV=production \
      APTUS_SECRET_KEY=secretref:secret-key \
      APTUS_DATABASE_URL=secretref:db-url \
      APTUS_ALLOWED_ORIGINS=https://your-frontend.example.edu.au \
      APTUS_REQUIRE_EMAIL_VERIFICATION=false
```

Generate the secret key with:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Four things that matter here:

- **`--target-port 8080`.** The image listens on 8080. Get this wrong
  and ingress returns 502 with the container perfectly healthy.
- **`--min-replicas 1`.** Scale-to-zero means a cold start on the first
  request, which is a poor first impression during a demo.
- **`secretref:`** keeps credentials out of theenvironment listing. Values set
  with `--secrets` are not readable back.
- **`sslmode=require`.** Azure PostgreSQL enforces TLS; without it the
  connection is refused.

`APTUS_ENGINE_CONFIG_DIR` is already baked into the image. Do not set it.

### Doing it in the portal instead

Container Apps → Create. Then: **Container** tab → image source *Docker
Hub or other registry*, type *Private*, server `docker.io`, image
`YOUR_USERNAME/ldap-be:staging`, with your username and token.
**Ingress** tab → enable, *Accepting traffic from anywhere*, **target
port 8080**. Environment variables and secrets go under the container's
settings, same names as above.

## 6. Test the deployment

```bash
URL=$(az containerapp show --name aptus-backend --resource-group aptus-staging \
      --query properties.configuration.ingress.fqdn -o tsv)

curl https://$URL/health     # {"status":"ok"}
curl https://$URL/version    # engine config version and digest
curl https://$URL/rls        # {"enforced": true, "role": "aptus_app", ...}
```

**`/rls` is the one that matters.** `enforced: true` with `role:
aptus_app` means the database is enforcing tenant isolation. Anything
else and the app would have refused to start — but check, and keep the
output. It is the answer to an institutional reviewer asking how you
know tenants are isolated.

Then run the full walkthrough against it:

```bash
./scripts/demo.sh https://$URL
```

Seventeen narrated steps ending in a pass/fail count. Expect 36 passed.

To make the pathway return mappings, seed the demonstration references
first (every code starts with `DEMO` and is marked unverified, on
purpose):

```bash
python scripts/seed-demo-references.py \
  "postgresql+psycopg://aptus_owner:<owner-password>@aptus-staging-db.postgres.database.azure.com:5432/aptus?sslmode=require"
```

## 7. Deploying a new build

```bash
# Actions → build-and-push → Run workflow (tag: staging)
az containerapp update --name aptus-backend --resource-group aptus-staging \
  --image docker.io/YOUR_USERNAME/ldap-be:staging
```

Container Apps does not re-pull a tag whose name has not changed, so
updating to the same tag may be a no-op. Deploy the commit tag instead
when you need certainty:

```bash
az containerapp update --name aptus-backend --resource-group aptus-staging \
  --image docker.io/YOUR_USERNAME/ldap-be:<commit-sha-tag>
```

Run migrations **before** updating the image whenever a release contains
one.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| 502 from ingress, container healthy | `--target-port` is not 8080 |
| Container restarts in a loop | Read the logs: startup validation says exactly what is wrong |
| `Row-level security is not enforced` at boot | App is connecting as a superuser or `BYPASSRLS` role |
| `SQLite is not supported in production` | `APTUS_DATABASE_URL` is unset or wrong |
| `no email adapter is configured` | Set `APTUS_REQUIRE_EMAIL_VERIFICATION=false` for staging |
| Connection refused to the database | Missing `sslmode=require`, or the firewall rule |

```bash
az containerapp logs show --name aptus-backend --resource-group aptus-staging --follow
```

## Before this holds real learner data

- **Residency.** `australiaeast` keeps compute and data in Sydney, which
  is what NFR-06 commits to. Confirm where backups are stored before a
  pilot — cross-border disclosure is an APP 8 question, not a detail.
- **Email.** `APTUS_REQUIRE_EMAIL_VERIFICATION=false` means email
  ownership is never proven. Acceptable for a closed staging URL you
  hand out; not acceptable for anything publicly reachable, where
  anyone could create an organisation against an address they do not
  control.
- **Separate databases.** Staging and production must not share one.
  The staging database holds demonstration reference data with
  deliberately fake unit codes.
- **Backups.** Flexible Server takes automatic backups; confirm the
  retention window suits you, and test a restore before you need one.
