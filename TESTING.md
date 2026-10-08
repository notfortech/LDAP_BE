# Testing what is built

Three levels, shortest first. All of them run against PostgreSQL —
SQLite has no row-level security, and testing tenant isolation on a
database that cannot enforce it is worse than not testing it.

## 0. One-time setup

```bash
docker compose up -d          # PostgreSQL 16 on localhost:5432
./scripts/setup-db.sh         # creates roles, runs migrations, prints posture
```

The script finishes by printing the security posture. You want:

```
aptus_app superuser=false bypassrls=false
candidates: rls=true forced=true          (and four more)
```

If `superuser` is `true`, row-level security is not protecting anything
— see level 3.

Then start the API:

```bash
cd api
pip install -e ../engine
pip install -e ".[dev,postgres]"

export APTUS_ENV=production
export APTUS_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
export APTUS_DATABASE_URL="postgresql+psycopg://aptus_app:apppw@localhost:5432/aptus"
export APTUS_ALLOWED_ORIGINS="http://localhost:5173"
export APTUS_ENGINE_CONFIG_DIR="$PWD/../engine/config/v1.0.0"
export APTUS_REQUIRE_EMAIL_VERIFICATION=false   # no email adapter ships yet

uvicorn aptus_api.main:create_app --factory --reload
```

Running with `APTUS_ENV=production` deliberately: it exercises the
fail-closed checks. If anything is misconfigured it refuses to start and
says why, which is the behaviour you want to see working.

## 1. The automated suite — 97 tests, about 25 seconds

```bash
cd api
export APTUS_TEST_APP_DATABASE_URL="postgresql+psycopg://aptus_app:apppw@localhost:5432/aptus"
export APTUS_TEST_ADMIN_DATABASE_URL="postgresql+psycopg://aptus_owner:ownerpw@localhost:5432/aptus"
pytest -q

cd ../engine && pytest -q    # 25 more: the scoring engine
```

Without those two variables the 13 row-level-security tests skip rather
than fail, and the output says so. A green run that skipped them has not
tested isolation.

What the suites cover:

| File | Proves |
|---|---|
| `test_settings.py` | Production refuses to start on unsafe configuration |
| `test_auth.py` | Signup, verification, sessions, enumeration resistance |
| `test_tenancy.py` | Every org-scoped endpoint refuses the wrong tenant |
| `test_rls.py` | The database enforces isolation, not just the code |
| `test_flow.py` | Invite → assess → score → passport → pathway |
| `test_content.py` | Item bank and engine configuration agree |
| `test_hardening.py` | Rate limits, security headers, CORS |
| `test_migrations.py` | Migrations produce the schema the models declare |
| `engine/tests/` | Determinism, band boundaries, config integrity |

## 2. The walkthrough — see it work

```bash
./scripts/demo.sh                        # defaults to http://127.0.0.1:8000
./scripts/demo.sh https://your-app.fly.dev
```

Seventeen steps, each printing what it is proving before it calls the
endpoint, ending in a pass/fail count. This is the one to run in front
of someone: it shows self-serve signup, the seat cap, the assessment,
determinism, the passport, the pathway, and two real institutions
unable to see each other.

To make the pathway return actual mappings first:

```bash
python scripts/seed-demo-references.py \
  "postgresql+psycopg://aptus_owner:ownerpw@localhost:5432/aptus"
```

Every seeded code starts with `DEMO` and is marked unverified, on
purpose. Real entries are typed in by a person who read the public
training.gov.au page; plausible-looking fake codes would eventually put
a non-existent unit in front of a learner.

**If the script stops saying signup is rate limited**, that is the
limiter working. It is in-process, so restart the API to clear it.

## 3. Row-level security — the part worth checking yourself

Enabling policies is not the same as being protected by them.
PostgreSQL lets a superuser, a `BYPASSRLS` role, or the table owner
without `FORCE` bypass every policy **silently**. Verify, do not assume.

**Ask the running service:**

```bash
curl localhost:8000/rls
```

`{"enforced": true, "role": "aptus_app", ...}` with an empty `problems`
list. This is also the answer to an institutional reviewer asking how
you know tenants are isolated.

**See it in the database:**

```bash
psql "postgresql://aptus_app:apppw@localhost:5432/aptus"
```

```sql
SET app.current_organisation = '1';
SELECT id, organisation_id, email FROM candidates;   -- org 1 only

SET app.current_organisation = '2';
SELECT id, organisation_id, email FROM candidates;   -- org 2 only

RESET app.current_organisation;
SELECT count(*) FROM candidates;                     -- 0. default-deny

SET app.current_organisation = '1';
INSERT INTO candidates (organisation_id, email, invited_at)
VALUES (2, 'smuggled@example.edu.au', now());        -- refused by policy
```

The last one should fail with *new row violates row-level security
policy*. If any of these behaves differently, isolation is not working
— check you connected as `aptus_app` and not as a superuser.

## 4. Packaged install — catches deployment-only defects

```bash
./scripts/smoke-packaged.sh "postgresql+psycopg://aptus_app:apppw@localhost:5432/aptus"
```

Installs non-editable into a throwaway venv and boots from outside the
checkout. Three defects reached main that the normal suite could not
see, because an editable install resolves paths a real one does not: a
missing engine configuration, an unpackaged item bank, and a candidate
credential on an RLS-protected table. Run this before any deploy.

## What is not covered

Honest list, so nobody assumes otherwise:

- **No load or performance testing.** NFR-02 states a 2s p95 target;
  nothing measures it yet.
- **No accessibility testing.** WCAG 2.2 AA is a stated requirement and
  an entry condition for public-provider sales. There is no frontend in
  this repository to test.
- **No email delivery.** No adapter ships, so verification is untested
  end to end.
- **No penetration test.** The suite tests the controls that exist; it
  does not look for the ones that are missing.
- **Rate limiting is per-process.** Across several API processes each
  keeps its own counter, so the effective limit multiplies.
