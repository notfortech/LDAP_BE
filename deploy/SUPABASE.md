# Supabase free tier as the demo database

Free, real PostgreSQL, full row-level security.

**This file covers the database only.** For the whole deployment —
Render for compute, Supabase for data — see **[RENDER.md](RENDER.md)**,
which is the path to follow.

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
- **Move off the free tier before a pilot.** No point-in-time restore,
  modest connection limits, and projects pause when idle. A new Azure
  account includes 750 hours of Burstable B1ms PostgreSQL free for 12
  months, which is worth checking if an Australian-region managed
  database becomes a requirement.
