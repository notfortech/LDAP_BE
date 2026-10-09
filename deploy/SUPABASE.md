# Supabase free tier as the demo database

Free, real PostgreSQL, full row-level security. Pairs with the Azure
Container App in `AZURE.md` — this replaces only the database.

## Why this works, given Supabase's `postgres` role bypasses RLS

Supabase's `postgres` role carries `BYPASSRLS`, so it ignores every
policy. That sounds fatal and is not, because this backend already
separates two roles:

| Role | Job | Needs to bypass RLS? |
|---|---|---|
| `postgres` (Supabase's) | Runs migrations. DDL. | Yes, and it does. Fine. |
| `aptus_app` (you create it) | The runtime connection. | **No — and it must not.** |

Policies apply to the role the application connects as. Create
`aptus_app` without `BYPASSRLS`, point the app at it, and isolation is
enforced exactly as on any other PostgreSQL.

The application verifies this at startup and refuses to boot in
production if its own role would bypass policies, so a mistake here
fails loudly rather than silently. `GET /rls` reports the live state.

## 1. Create the project

supabase.com → New project. **Region: Sydney (`ap-southeast-2`)** if
offered — compute is in `australiaeast` and keeping data in the same
country is what NFR-06 commits to.

Save the database password; you need it for migrations.

## 2. Get the right connection strings

Project → **Connect**. Three are offered and the difference matters:

| Mode | Host / port | IPv4? | Use for |
|---|---|---|---|
| Direct | `db.<ref>.supabase.co:5432` | **No — IPv6 only** | nothing here |
| Session pooler | `...pooler.supabase.com:5432` | Yes | migrations |
| Transaction pooler | `...pooler.supabase.com:6543` | Yes | the running app |

**Do not use the direct connection.** It is IPv6-only unless you buy the
IPv4 add-on, and Azure Container Apps egress is IPv4. It will simply
fail to resolve.

Convert the string for psycopg: replace the `postgresql://` scheme with
`postgresql+psycopg://`.

## 3. Create the application role

SQL Editor → paste `deploy/02-supabase-roles.sql`, replace the password,
run it.

The last statement prints the role's attributes. **`rolsuper` and
`rolbypassrls` must both be `false`.** If either is true, stop — the
application would have no tenant isolation, and it will refuse to start.

`01-roles.sql` does **not** work here: hosted Supabase rejects
`ALTER ROLE ... NOSUPERUSER` (SQLSTATE 42501) and will not let you
re-own `public`. The Supabase script sets every attribute at
`CREATE ROLE` instead, which is permitted.

## Prerequisites

The script needs `az` and `docker` **in the same shell it runs in**. On
Windows that is the usual trap: the Azure CLI installed in PowerShell
while the script runs under WSL or Git Bash, where it is not on PATH.

```bash
az version && docker version     # both must answer in this terminal
az login --use-device-code       # plain 'az login' cannot open a browser
az account show                  # confirms the session
```

Use `--use-device-code` in WSL, over SSH, in a devcontainer or in
Codespaces: the CLI has no browser to open there, so plain `az login`
hangs. It prints a code and a URL to open anywhere.

If VS Code's bottom-left corner says WSL, Dev Container or SSH, your
terminal is on that machine, and both tools must be installed there.

## Shortcut: one script for steps 4-6

`scripts/deploy-azure.sh` does the migrations, the Container App and the
verification in one run. Copy it, fill in the block at the top, run it:

```bash
cp scripts/deploy-azure.sh deploy-azure.local.sh   # gitignored
$EDITOR deploy-azure.local.sh
./deploy-azure.local.sh
```

It stops at the first failure with the reason, and every step is
idempotent, so a half-finished run can be fixed and re-run. The manual
steps below are the same thing if you would rather do it by hand.

## 4. Run the migrations

Over the **session** pooler, as `postgres`, from the published image —
same Alembic, same migrations, nothing to drift:

```bash
docker run --rm \
  -e APTUS_ENV=development \
  -e APTUS_DATABASE_URL="postgresql+psycopg://postgres.<ref>:<db-password>@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres" \
  YOUR_USERNAME/ldap-be:staging \
  sh -c 'cd /srv/api && alembic upgrade head'
```

Five migrations should apply. Then grant the app role rights on the
tables they just created (the default privileges in step 3 cover every
later migration):

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO aptus_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO aptus_app;
```

## 5. Point the Container App at the transaction pooler

```bash
az containerapp secret set \
  --name aptus-backend --resource-group aptus-staging \
  --secrets db-url='postgresql+psycopg://aptus_app:<app-password>@aws-0-ap-southeast-2.pooler.supabase.com:6543/postgres'

az containerapp update \
  --name aptus-backend --resource-group aptus-staging \
  --set-env-vars APTUS_DATABASE_URL=secretref:db-url
```

The backend detects a transaction pooler from the URL and adjusts
automatically: prepared statements off, client-side pooling disabled.
Both are required — a transaction pooler gives each transaction a
different backend, so a prepared statement from one is unknown to the
next (`prepared statement "_pg3_0" already exists`), and a client-side
pool only consumes the pooler's limited slots.

Override with `APTUS_DB_TRANSACTION_POOLER=true|false` if detection ever
gets it wrong. The choice is logged at startup.

### Keeping the demo cheap

Supabase free is free. The Container App is not, at the spec in
`AZURE.md`. For a demo:

```bash
az containerapp update --name aptus-backend --resource-group aptus-staging \
  --cpu 0.25 --memory 0.5Gi --min-replicas 0 --max-replicas 1
```

Scale-to-zero costs a few seconds on the first request. Warm it with a
`curl` before a demo.

## 6. Verify

```bash
URL=$(az containerapp show --name aptus-backend --resource-group aptus-staging \
      --query properties.configuration.ingress.fqdn -o tsv)

curl https://$URL/health
curl https://$URL/version
curl https://$URL/rls      # the one that matters
```

`/rls` must report `"enforced": true` with `"role": "aptus_app"`. On
Supabase specifically, check this rather than assume: it is the
difference between policies that apply and policies that are ignored.

Then the full walkthrough:

```bash
./scripts/demo.sh https://$URL      # expect 36 passed
```

Seed the demonstration references first if you want the pathway to
return mappings — over the **session** pooler as `postgres`, since
global rows are maintained outside any tenant:

```bash
python scripts/seed-demo-references.py \
  "postgresql+psycopg://postgres.<ref>:<db-password>@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"
```

## Free tier limits worth knowing

- **Projects pause after about a week of inactivity** and need a manual
  resume from the dashboard. Before a scheduled demo, open the project
  and run a query the day before.
- Storage and connection limits are modest. Fine for a demo cohort,
  not for a pilot with real throughput.
- No point-in-time restore on the free plan. Do not let a demo quietly
  become the pilot — see below.

## Before real learner data

- **Confirm the region.** A free-tier project in Singapore rather than
  Sydney is a residency problem the moment a real cohort exists, not a
  detail. APP 8 governs cross-border disclosure.
- **Supabase Auth is not used and should not be.** This backend has its
  own authentication: scrypt passwords, opaque revocable session tokens,
  and tenant context set per transaction. Adding Supabase Auth would
  mean two identity systems disagreeing about who a caller is.
- **PostgREST is not used either.** Supabase exposes a REST API over
  your tables. The backend does not use it, and nothing should: that
  path authenticates as `anon` or `authenticated`, which this schema has
  no policies for. Leave those roles without grants on these tables.
- **Move to a paid plan or Azure Flexible Server before a pilot.** A new
  Azure account includes 750 hours of B1ms PostgreSQL free for 12
  months, which is the same database `AZURE.md` describes at no cost —
  worth checking your eligibility.
