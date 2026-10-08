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

## Known limitations

- **Rate limiting is in-process.** Across several API processes each
  holds its own counter, so the effective limit multiplies by process
  count. Acceptable at single-node appliance scale; a multi-node
  deployment needs a shared store.
- **Tenant isolation is application-layer.** Row-level security in
  PostgreSQL is the next step and is the precondition for any shared
  managed tier.
- **No email adapter ships.** Development logs the verification token.
  Production refuses to start a flow it cannot deliver, rather than
  dropping mail silently.
