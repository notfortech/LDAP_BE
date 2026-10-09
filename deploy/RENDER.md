# Deploying: Render + Supabase

Compute on Render, database on Supabase. Both free. No Azure, no Fly.

You already run `aptus-api` (the old backend) and `aptus-demo` (the
frontend) on Render, so this adds one more service alongside them rather
than introducing a platform.

**This does not touch the existing demo.** New Render service, new
Supabase project, nothing shared.

---

## Before you start

- A **new** Supabase project (not the one `aptus-api` uses — three table
  names collide with incompatible columns).
- The `aptus_app` role created in it, from `deploy/02-supabase-roles.sql`.
  Verify `rolsuper` and `rolbypassrls` are both `false`.
- The image published: GitHub → Actions → **build-and-push** → tag
  `staging`.

## 1. Migrations

From your machine, using the published image. Migrations need DDL
rights; the running service deliberately has none, which is why this is
a separate step rather than something the container does at boot.

```bash
git pull
./scripts/migrate.sh YOUR_DOCKERHUB_USER/ldap-be:staging \
  "postgresql+psycopg://postgres.YOUR_REF:YOUR_DB_PASSWORD@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"
```

**Port 5432 — the session pooler.** Transaction mode (6543) cannot hold
a session across a DDL run. The script refuses 6543 rather than letting
you find out halfway through.

Supabase → Connect → *Session pooler*, and change the scheme to
`postgresql+psycopg://`.

Expect five `Running upgrade` lines. Then paste the two `GRANT`
statements it prints into the Supabase SQL Editor.

## 2. Create the Render service

**Dashboard:** New → Web Service → connect `notfortech/LDAP_BE`.

| Setting | Value |
|---|---|
| Name | `aptus-be` |
| Language / Runtime | **Docker** |
| Dockerfile path | `./Dockerfile` |
| Docker build context | `.` (repository root) |
| Region | Singapore (closest to Australia) |
| Instance type | Free |
| Health check path | `/health` |

The build context must be the repository root: the image needs both
`engine/` and `api/`, because the API imports the engine package.

**Or via blueprint:** `render.yaml` in this repository records the same
settings. Dashboard → Blueprints → New Blueprint Instance.

## 3. Environment variables

Render → your service → Environment.

| Key | Value |
|---|---|
| `APTUS_ENV` | `production` |
| `APTUS_SECRET_KEY` | click **Generate** |
| `APTUS_DATABASE_URL` | the **transaction pooler** string, as `aptus_app` |
| `APTUS_ALLOWED_ORIGINS` | `https://aptus-demo.onrender.com,http://localhost:5173` |
| `APTUS_REQUIRE_EMAIL_VERIFICATION` | `false` |

The database URL here is **port 6543**, and the user is `aptus_app`, not
`postgres`:

```
postgresql+psycopg://aptus_app:APP_PASSWORD@aws-0-ap-southeast-2.pooler.supabase.com:6543/postgres
```

Two ports, two roles, deliberately: `postgres` on 5432 for migrations,
`aptus_app` on 6543 for the running service. `aptus_app` has no DDL
rights, so a compromised runtime connection cannot drop a policy.

Do **not** set `PORT` — Render injects it and the container binds to it.
Do **not** set `APTUS_ENGINE_CONFIG_DIR` — it is baked into the image.

## 4. Deploy and verify

```bash
URL=https://aptus-be.onrender.com      # your actual service URL

curl $URL/health      # {"status":"ok"}
curl $URL/version     # engine config version and digest
curl $URL/rls         # the one that matters
```

`/rls` must report `"enforced": true` with `"role": "aptus_app"`.

If it says anything else the service would have refused to start, so a
running service that answers `/health` has already passed this check —
but look at it anyway and keep the output. It is the answer to an
institutional reviewer asking how you know tenants are isolated.

## 5. Walk through every feature

```bash
python3 scripts/seed-demo-references.py \
  "postgresql+psycopg://postgres.YOUR_REF:YOUR_DB_PASSWORD@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"

./scripts/demo.sh $URL
```

Seventeen narrated steps, ending in a pass/fail count. **Expect 36
passed.** It covers self-serve signup, enumeration resistance, the seat
cap, the assessment, determinism, the passport, the pathway, and two
real institutions unable to see each other.

Seed over the **session** pooler as `postgres`: global reference rows
are maintained outside any tenant, and `aptus_app` is correctly refused.

Every seeded unit code starts with `DEMO` and is marked unverified, on
purpose — real entries are typed in by a person reading the public
training.gov.au page.

## Two things that will bite during a demo

**Render free spins down after ~15 minutes idle.** The first request
then takes 30-60 seconds. Warm it with a `curl` a minute before you
present.

**Supabase free projects pause after about a week idle** and need a
manual resume from the dashboard. Open the project the day before.

Both are free-tier behaviour, not faults. Together they mean: never open
a demo by loading the app cold.

## Updating

```bash
# GitHub -> Actions -> build-and-push (tag: staging)
# Render -> your service -> Manual Deploy -> Deploy latest reference
```

`autoDeploy` is off deliberately, so a push to `main` does not change
what you are about to demo. Run migrations first whenever a release
contains one.

## Before real learner data

- **Region.** Render's closest region to Australia is Singapore, and a
  free Supabase project may also be outside Australia. NFR-06 commits to
  Australian residency, and APP 8 governs cross-border disclosure. This
  is a demo-only arrangement.
- **Email verification is off**, so email ownership is never proven.
  Fine for a URL you hand out; not for a public one.
- **No point-in-time restore** on either free tier.
