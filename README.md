# LDAP_BE — Aptus backend

Backend for the Aptus Capability Intelligence Platform: a deterministic
capability assessment engine and the service that exposes it.

## Layout

```
engine/     Deterministic scoring engine — pure Python, no dependencies,
            versioned configuration, generated evidence basis
api/        FastAPI service — self-serve organisations, sessions,
            tenant-scoped access
```

## Principles

These are load-bearing. Everything else is subordinate to them.

1. **Determinism over inference.** No language model participates in any
   score, ever. Scoring is a pure function of responses and versioned
   configuration — no clock, no randomness, no I/O. A golden-master
   suite enforces this on every build.
2. **Traceability.** Every result records the configuration version and
   a SHA-256 digest of the configuration that produced it, so any
   historical result can be reproduced exactly.
3. **No automated contact with framework sources.** Nothing in this
   system makes requests to training.gov.au, ACARA, the ABS or Jobs and
   Skills Australia. Reference data is human-entered and versioned.
4. **Tenant isolation as a trust gate.** Every record is organisation-
   scoped. No query path may return another tenant's rows.
5. **Honest positioning.** The platform measures capability and
   behavioural signal. It is not a validated psychometric instrument and
   is never described as one. See `engine/EVIDENCE.md`.

## Testing

Deploy with `scripts/deploy-azure.sh` (see **[deploy/SUPABASE.md](deploy/SUPABASE.md)**).

See **[TESTING.md](TESTING.md)** — automated suites, a narrated
walkthrough (`./scripts/demo.sh`), how to verify row-level security
yourself in psql, and an honest list of what is not covered.

## Getting started

```bash
cd engine
pip install -e ".[dev]"
pytest
```

## Status

| Component | State |
|---|---|
| Deterministic engine | Built — 25 tests, determinism gate in CI |
| Evidence basis | Built — generated from configuration |
| API service | Built — self-serve signup, sessions, organisation scoping |
| Organisations and membership | Built — organisation entity, owner/admin roles |
| Authentication hardening | Built — fail-closed config, opaque sessions, scrypt |
| Database migrations | Built — Alembic, drift-checked in CI |
| Cross-tenant isolation (application layer) | Built — release gate in CI |
| Assessment-to-pathway flow | Built — invite, assess, score, passport, pathway |
| Reference library (global + org fork, versioned) | Built — model and resolver |
| Row-level security (database layer) | Built — policies, posture guard, 13 tests on real PostgreSQL |
| Deployment | Built — Dockerfile (verified), Docker Hub workflow, deploy/AZURE.md, deploy/SUPABASE.md, deploy/FLY.md |
| Colleague invitation | Not started |

The backlog driving the remaining work is the backend story set: an
eight-story MVP covering the organisation model, self-serve signup, the
auth boundary, tenant-isolation testing, rate limiting and migrations.
