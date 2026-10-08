# aptus-api

FastAPI service for self-serve institutional use.

## The architecture this is built around

An institution signs itself up, verifies its email, and runs its own
cohort — without anyone provisioning it by hand. That removes a control
the predecessor relied on, so the controls below replace it.

### Organisation identity never comes from the client

The predecessor used the inviting administrator's own user id as the
tenant key, and separately accepted an `org_id` in the request body as a
development convenience. Both are gone. An organisation is its own
entity, access is granted by a `memberships` row, and the
`{organisation_id}` in a path only selects among the caller's own
memberships — it can never grant one.

A non-member receives **404, not 403**. A 403 confirms the organisation
exists, which lets an outsider enumerate the tenant list by walking ids.

### Configuration fails closed

The predecessor's authentication became a no-op when its identity
variables were absent. Here, production refuses to start without a
secret key, a non-SQLite database and an explicit origin list. There is
no state where security is configured but optional.

### Sessions are opaque and revocable

A session token is 32 random bytes, shown once, stored only as a
SHA-256 digest. A database disclosure yields no usable credential, and
sign-out revokes immediately — which a self-contained signed token
cannot do.

Passwords use `hashlib.scrypt` at RFC 7914 interactive parameters. No
third-party cryptography, so the appliance profile installs without
reaching outside the standard library for anything security-critical.

### Signup reveals nothing

Signing up with an address that already exists returns the same response
as a fresh one. Signing in with a wrong password returns the same error
as an unknown address, after the same hashing work, so neither the body
nor the timing identifies who holds an account.

## Running

```bash
pip install -e ".[dev]"
cp .env.example .env          # fill in, or leave for development defaults
alembic upgrade head
uvicorn aptus_api.main:create_app --factory --reload
```

Schema comes from Alembic, never from `create_all` at import.

## Tests

```bash
pytest
```

`tests/test_tenancy.py` is a release gate. It calls every
organisation-scoped endpoint as the wrong tenant and fails the build on
anything but a 404. Its final test fails when a new organisation-scoped
route exists that the suite does not cover — add the route to
`ORG_SCOPED`, do not delete the test.

That coverage test reads routes from the OpenAPI schema rather than
walking `app.routes`, because included routers are not always flattened
and a route walk can silently find nothing. It asserts discovery is
non-empty for the same reason: a suite that passes because it tested
zero endpoints is worse than no suite.

## The assessment-to-pathway flow

```
admin invites candidate      POST /orgs/{org}/candidates      -> access token, once
admin assigns constructs     PUT  .../assignments             -> narrows the item set
candidate fetches items      GET  /assessment/full            -> candidate token
candidate submits            POST /assessment/full/submit     -> engine scores it
admin reads passport         GET  /orgs/{org}/candidates/{id} -> longitudinal record
admin generates pathway      GET  .../pathway                 -> real units of competency
```

Four things this flow guarantees:

- **Candidates are not users.** They hold no password and cannot sign
  in. A candidate token grants access to exactly one assessment —
  their own — and carries no organisation scope a caller can widen.
- **Responses are filtered to the items actually served.** A candidate
  assigned two constructs cannot be scored on twelve by submitting
  answers they were never shown.
- **Every attempt records the engine configuration digest** that scored
  it, so a result stays reproducible after the engine moves on.
- **Practice never reaches the passport**, and never produces a
  pathway. A document handed to a learner comes from the assessment
  that counts.

The Recommended Pathway resolves an organisation's forked reference
entries **in place of** the global defaults they diverged from, rather
than alongside them, and reports unverified mappings and constructs with
no mapping rather than hiding either.

## Row-level security

Tenant isolation is enforced by PostgreSQL, not only by the WHERE
clauses the application remembers to write. Policies on `candidates`,
`candidate_assignments`, `assessment_attempts`,
`attempt_construct_scores` and `training_references` compare
`organisation_id` against a per-connection parameter the request sets
once membership is proven.

**Enabling RLS is not the same as being protected by it.** PostgreSQL
lets three things bypass every policy silently, with no warning:

- a superuser connection;
- a role with `BYPASSRLS`;
- the table owner, unless the table is set to `FORCE ROW LEVEL SECURITY`.

All three fail open. The application therefore refuses to start in
production if it detects any of them, and `GET /rls` reports the live
posture so a reviewer can check rather than take the claim on trust.

Run the app as `aptus_app`: not a superuser, no `BYPASSRLS`, owns
nothing, and holds data rights only — so it cannot drop a policy.
Migrations run as `aptus_owner`. `scripts/setup-db.sh` creates both.

Two details worth knowing:

- Policies compare against an `app_current_organisation()` accessor
  rather than casting the parameter inline. A bare `::int` cast raises
  on any non-numeric value, turning a tenancy question into a 500
  instead of a clean denial.
- Maintaining the shared global reference library needs its own path,
  because `FORCE` applies to the owner too. A connection must set the
  parameter to the literal `global`; a request serving a tenant has it
  set to a number, so it can never reach a global row.

## Known limitations

- **Rate limiting is in-process.** Across several API processes each
  holds its own counter, so the effective limit multiplies by process
  count. Acceptable at single-node appliance scale; a multi-node
  deployment needs a shared store.
- **No email adapter ships.** Development logs the verification token.
  Production refuses to start a flow it cannot deliver, rather than
  dropping mail silently.
