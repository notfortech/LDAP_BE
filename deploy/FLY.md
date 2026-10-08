# Deploying to Fly.io

Sydney region, Managed Postgres, one machine. Roughly fifteen minutes
from nothing to a working URL.

## Before you start

Fly has two Postgres products. **Use Managed Postgres (MPG).** The older
"Fly Postgres" is unmanaged, no longer maintained, and Fly support will
not help with it. Sydney (`syd`) is an MPG region, but confirm with
`fly platform regions` — the list changes.

> **Verify before an institutional pilot.** A community report says
> backups for `syd` land in `ap-southeast-1` (Singapore). It is a forum
> post, not documentation, and unconfirmed — but your BRD commits to
> Australian data residency (NFR-06) and APP 8 governs cross-border
> disclosure. Ask Fly support to confirm in writing where backups are
> stored before you put a TAFE's learner data in it. If the answer is
> Singapore, that is a residency problem, not a detail.

## 1. Create the app and database

```bash
fly auth login
fly apps create aptus-backend                      # name must match fly.toml
fly mpg create --name aptus-db --region syd        # confirm the region first
```

## 2. Create the roles

The application connects as a role that **cannot** bypass row-level
security. This is the whole basis of tenant isolation: a superuser or
`BYPASSRLS` connection ignores every policy silently. The app refuses to
start if it detects that, but create the roles correctly anyway.

Connect as the database superuser and run:

```bash
fly mpg connect --cluster aptus-db
```

```sql
CREATE ROLE aptus_owner LOGIN PASSWORD '<owner-password>'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE aptus_app   LOGIN PASSWORD '<app-password>'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

GRANT CONNECT ON DATABASE <dbname> TO aptus_owner, aptus_app;
ALTER SCHEMA public OWNER TO aptus_owner;
GRANT USAGE ON SCHEMA public TO aptus_app;

ALTER DEFAULT PRIVILEGES FOR ROLE aptus_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO aptus_app;
ALTER DEFAULT PRIVILEGES FOR ROLE aptus_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO aptus_app;
```

`deploy/01-roles.sql` is the same thing as a script.

## 3. Set secrets

Two database URLs, deliberately. Migrations need DDL rights; the runtime
must not have them, so a compromised runtime connection cannot drop a
policy.

```bash
fly secrets set \
  APTUS_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  APTUS_DATABASE_URL="postgresql+psycopg://aptus_app:<app-password>@<host>:5432/<dbname>" \
  APTUS_MIGRATION_DATABASE_URL="postgresql+psycopg://aptus_owner:<owner-password>@<host>:5432/<dbname>" \
  APTUS_ALLOWED_ORIGINS="https://your-frontend.example.edu.au"
```

`fly mpg status aptus-db` gives the host. Keep the `+psycopg` driver
prefix; a bare `postgresql://` URL selects a driver that is not
installed.

## 4. Deploy

```bash
fly deploy
```

The release command runs `alembic upgrade head` as `aptus_owner` before
the new version takes traffic. After the first deploy, grant the app
rights on the tables the migration just created (the default privileges
above cover every later migration):

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO aptus_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO aptus_app;
```

## 5. Verify

```bash
curl https://aptus-backend.fly.dev/health      # {"status":"ok"}
curl https://aptus-backend.fly.dev/version     # engine config + digest
curl https://aptus-backend.fly.dev/rls         # {"enforced": true, ...}
```

**`/rls` is the one that matters.** `enforced: true` with `role:
aptus_app` means the database is enforcing tenant isolation. Anything
else and the app would have refused to boot — but check, and keep the
output: it is the answer to an institutional reviewer asking how you
know tenants are isolated.

## Email

The default requires email verification, and the app refuses to start in
production without a way to send it. No adapter ships yet, so for a
closed pilot:

```bash
fly secrets set APTUS_REQUIRE_EMAIL_VERIFICATION=false
```

Organisations then activate on signup without proving email ownership.
**Do not do this on a publicly reachable deployment** — anyone can
create an organisation against an address they do not control. For a
pilot where you hand out the URL, it is fine.

## Cost

One `shared-cpu-1x` 512MB machine plus the smallest MPG cluster is
roughly US$10–20/month at the time of writing. `min_machines_running = 1`
keeps the machine warm: a cold start during a demo is a bad first
impression, and the saving is pennies.

## What is deliberately not here

No object storage, no queue, no cache, no secrets manager. The
architecture has no need of them, and each would be another dependency
the self-hosted appliance profile cannot assume.
